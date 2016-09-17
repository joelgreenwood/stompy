#!/usr/bin/env python
"""
This server should implement something like this:
http://wiki.ros.org/joint_trajectory_controller/UnderstandingTrajectoryReplacement

It needs to:
    - if an empty trajectory arrives, the goal is canceled
    - if a trajectory with a blank timestamp arrives, start it now
    - if a new trajectory (b) arrives during a trajectory (a), merge it:
        - if b start time is now, drop all later points from a
        - if start time is in future, drop all points after b start time
        - if b start time is in past:
          drop all later points for a, and earlier points for b

Also, it will need to buffer points sent to the teensy allowing:
    - sufficient data for the teensy for future waypoints
    - preemption of already buffered (sent) points
    - clearing/cancelation of trajectories

Finally, it will need to produce at a minimum a result and check for
various tolerances during movement. Ideally, it will also provide feedback
during movements (although the gazebo controller does not).

Result:
    - if a new trajectory is received, set as preempted and move on
    - if tolerances are exceeded, set as aborted
    - if trajectory is finished, set as succeeded
"""

import actionlib
import control_msgs.msg
import rospy
import trajectory_msgs.msg

import stompy.ros.leg


class LegPoint(object):
    def __init__(self, pid, positions, point_time):
        self.positions = positions
        self.point_time = point_time
        self.pid = pid
        self.teensy_index = -1

    def in_future(self, current_time):
        return self.point_time > current_time

    def was_sent(self):
        return self.teensy_index != -1

    def send(self):
        teensy_time = stompy.ros.leg.teensy.convert_ros_time(self.point_time)
        stompy.ros.leg.teensy.lock.acquire(True)
        self.teensy_index = stompy.ros.leg.teensy.mgr.blocking_trigger(
            'new_point', self.pid, teensy_time,
            self.positions[0], self.positions[1],
            self.positions[2])[0].value
        stompy.ros.leg.teensy.lock.release()

    def drop(self):
        if not self.was_sent():
            print("Attempt to drop non-sent point: %s" % self.pid)
            return
        stompy.rosl.leg.teensy.lock.acquire(True)
        stompy.ros.leg.teensy.mgr.trigger(self.teensy_index)
        stompy.ros.leg.teensy.lock.release()


class TrajectoryBuffer(object):
    """A buffer of points
    Points have a time and n positions"""
    def __init__(self):
        self._id = 0
        self._points = {}

    def __len__(self):
        return len(self._points)

    def next_id(self):
        self._id += 1
        if self._id > 255:
            self._id = 0
        return self._id

    def add_point(self, point_time, positions):
        pid = self.next_id()
        self._points[pid] = LegPoint(pid, positions, point_time)

    def drop_later_points(self, point_time):
        dropped = {}
        for pid in self._points.keys():
            if self._points[pid].in_future(point_time):
                dropped[pid] = self._points.pop(pid)
        return dropped

    def append_trajectory(self, trajectory):
        """Append a trajectory to the point buffer

        Return the point ids of points that were overwritten
        """
        # TODO tolerances
        # goal_time_tolerance, path_tolerance, goal_tolerance
        start_time = trajectory.header.stamp
        now = rospy.Time.now()
        if start_time.is_zero():
            start_time = rospy.Time.now()
        first = True
        dropped_points = {}
        for pt in trajectory.points:
            point_time = start_time + pt.time_from_start
            if point_time < now:
                print("Dropping point in past: %s" % point_time)
                continue
            # merge points with current points
            if first:
                dropped_points = self.drop_later_points(point_time)
                #if len(dropped_points):
                #    pid = dropped_points[0].pid
                #    self.set_next_id(pid)
            self.add_point(point_time, pt.positions)
        return dropped_points

    def __getitem__(self, pid):
        return self._points[pid]

    def __delitem__(self, pid):
        if self._points[pid].was_sent():
            self._points[pid].drop()
        del self._points[pid]

    def __contains__(self, pid):
        return pid in self._points

    def keys(self):
        return self._points.keys()

    def remove_by_index(self, index):
        for pid in self._points:
            if self._points[pid].teensy_index == index:
                del self._points[pid]
                return
        raise KeyError("Cannot find point index for removal: %s" % index)

    def get_next_point_id(self):
        """Get the next trajectory point"""
        if len(self) == 0:
            return None
        return sorted(self._points.keys())[0]

    def get_next_unsent_point_id(self):
        for pid in sorted(self._points.keys()):
            if not self._points[pid].was_sent():
                return pid
        return None

    def drop_all(self):
        for pid in self._points:
            if self._points[pid].was_sent():
                self._points[pid].drop()
        self._points = {}


class JointTrajectoryActionServer(object):
    _feedback = control_msgs.msg.FollowJointTrajectoryFeedback
    _result = control_msgs.msg.FollowJointTrajectoryResult

    def __init__(self, name):
        self._action_name = name
        self._as = actionlib.SimpleActionServer(
            self._action_name, control_msgs.msg.FollowJointTrajectoryAction,
            execute_cb=self.execute_cb, auto_start=False)
        self._as.start()
        self._point_buffer = TrajectoryBuffer()

    def execute_cb(self, goal):
        # execute action
        success = True

        # TODO prep feedback
        # TODO check names = hip, thigh, knee
        names = goal.trajectory.joint_names
        print("Joint names: %s" % names)

        if len(goal.trajectory.points) == 0:
            self._point_buffer.drop_all()
            # TODO cancel, return something
            raise Exception("Invalid trajectory, no points")

        # combine new trajectory with existing one
        dropped_points = self._point_buffer.append_trajectory(goal.trajectory)
        # drop all these points on the teensy
        print("Dropping points: %s" % dropped_points.keys())
        for pid in dropped_points:
            if dropped_points[pid].was_sent():
                print("Request teensy to drop point: %s" % pid)
                dropped_points[pid].drop()

        success = True
        done = False
        buffer_duration = rospy.Duration(1.0)
        target_id = self._point_buffer.get_next_point_id()
        send_id = self._point_buffer.get_next_unsent_id()
        while not done and target_id is not None:
            # wait for trajectory to finish OR for trajectory to be canceled
            # OR for errors from teensy
            if self._as.is_preempt_requested():
                self._as.set_preempted()
                # check if a new goal was received
                if self._as.is_new_goal_available():
                    return
                else:
                    # there is no new goal, so stop moving
                    self._point_buffer.drop_all()
                    # TODO cancel, return something
                    return
                done = True
                break
            # check to see if target has been reached?
            for pindex in stompy.ros.leg.trajectories.points_reached[:]:
                # if so, remove it
                self._point_buffer.remove_by_index(pindex)
                stompy.ros.leg.trajectories.points_reached.remove(pindex)
            target_id = self._point_buffer.get_next_point_id()
            # check if more points should be sent
            now = rospy.Time.now()
            while send_id is not None:
                pt = self._point_buffer[send_id]
                if pt.point_time < now:
                    raise Exception("Point in past")
                # send at least 1 second worth of points
                if pt.point_time - now < buffer_duration:
                    # send point
                    pt.send()
                    send_id = self._point_buffer.get_next_unsent_id()
                else:
                    break

        if success:
            r = self._result()
            self._as.set_succeeded(r)


if __name__ == '__main__':
    rospy.init_node('action_server')
    topic = '/stompy/fr/follow_joint_trajectory'
    print("starting action server: %s" % topic)
    JointTrajectoryActionServer(topic)
    print("spinning...")
    rospy.spin()
