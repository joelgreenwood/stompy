#!/usr/bin/env python

import sys
import traceback

import numpy
from PyQt4 import QtCore, QtGui

from .. import body
from .. import calibration
from .. import consts
from .. import controllers
from . import base
from .. import joystick
from .. import kinematics
from .. import leg
from .. import log


class Tab(object):
    def __init__(self, ui, controller):
        self.ui = ui
        self.controller = controller
        if self.controller is not None:
            self._last_leg_index = None
            self.controller.on('set_leg', self.set_leg_index)
            self.set_leg_index(self.controller.leg_index)

    def set_leg_index(self, index):
        self._last_leg_index = index

    def start_showing(self):
        pass

    def stop_showing(self):
        pass


class PIDTab(Tab):
    n_points = 1000

    def __init__(self, ui, controller):
        self.chart = ui.pidLineChart
        self.chart.addSeries('Setpoint')
        self.chart.addSeries('Output')
        self.chart.addSeries('Error')

        super(PIDTab, self).__init__(ui, controller)
        # TODO make ui map
        self.joint_config = {}

        self.ui.pidJointCombo.currentIndexChanged.connect(
            self.change_joint)
        self.ui.pidCommitButton.clicked.connect(
            self.commit_values)

        self.change_joint()

    def set_leg_index(self, index):
        if self.controller is None:
            return
        if self._last_leg_index is not None:
            self.controller.legs[self._last_leg_index].remove_on(
                'pid', self.on_pid)
        super(PIDTab, self).set_leg_index(index)  # update index
        if index is not None:
            self.controller.leg.on(
                'pid', self.on_pid)

    def add_pid_values(self, output, setpoint, error):
        self.chart.appendData('Setpoint', setpoint)
        self.chart.appendData('Output', output)
        self.chart.appendData('Error', error)
        self.chart.update()
        return

    def on_pid(self, pid):
        txt = str(self.ui.pidJointCombo.currentText()).lower()
        o, s, e = pid['output'], pid['set_point'], pid['error']
        if txt not in o:
            return
        self.add_pid_values(o[txt], s[txt], e[txt])

    def change_joint(self):
        self.clear_pid_values()
        self.read_joint_config()

    def read_joint_config(self):
        # get current joint
        txt = str(self.ui.pidJointCombo.currentText())
        try:
            index = ['Hip', 'Thigh', 'Knee'].index(txt)
        except ValueError:
            return
        self.joint_config = {}
        if (
                self.controller.leg is None or
                not hasattr(self.controller.leg, 'mgr')):
            return self.joint_config
        # get all values for this joint
        # P, I, D, min, max
        r = self.controller.leg.mgr.blocking_trigger('pid_config', index)
        self.joint_config['pid'] = {
            'p': r[1].value,
            'i': r[2].value,
            'd': r[3].value,
            'min': r[4].value,
            'max': r[5].value,
        }

        # following error threshold
        r = self.controller.leg.mgr.blocking_trigger(
            'following_error_threshold', index)
        #print("Following error: %s" % r[1].value)
        self.joint_config['following_error_threshold'] = r[1].value

        # pwm: extend/retract min/max
        r = self.controller.leg.mgr.blocking_trigger('pwm_limits', index)
        self.joint_config['pwm'] = {
            'extend_min': r[1].value,
            'extend_max': r[2].value,
            'retract_min': r[3].value,
            'retract_max': r[4].value,
        }

        # adc limits
        r = self.controller.leg.mgr.blocking_trigger('adc_limits', index)
        self.joint_config['adc'] = {'min': r[1].value, 'max': r[2].value}

        # dither
        r = self.controller.leg.mgr.blocking_trigger('dither')
        self.joint_config['dither'] = {'time': r[0].value, 'amp': r[1].value}

        # seed time
        #r = self.controller.leg.mgr.blocking_trigger('pid_future_time')
        #self.joint_config['future_time'] = r[0].value

        # set ui elements by joint_config
        self.ui.pidPSpin.setValue(self.joint_config['pid']['p'])
        self.ui.pidISpin.setValue(self.joint_config['pid']['i'])
        self.ui.pidDSpin.setValue(self.joint_config['pid']['d'])
        self.ui.pidMinSpin.setValue(self.joint_config['pid']['min'])
        self.ui.pidMaxSpin.setValue(self.joint_config['pid']['max'])
        self.ui.extendMinSpin.setValue(self.joint_config['pwm']['extend_min'])
        self.ui.extendMaxSpin.setValue(self.joint_config['pwm']['extend_max'])
        self.ui.pidErrorThresholdSpin.setValue(
            self.joint_config['following_error_threshold'])
        self.ui.retractMinSpin.setValue(
            self.joint_config['pwm']['retract_min'])
        self.ui.retractMaxSpin.setValue(
            self.joint_config['pwm']['retract_max'])
        self.ui.adcLimitMinSpin.setValue(self.joint_config['adc']['min'])
        self.ui.adcLimitMaxSpin.setValue(self.joint_config['adc']['max'])
        self.ui.ditherTimeSpin.setValue(self.joint_config['dither']['time'])
        self.ui.ditherAmpSpin.setValue(self.joint_config['dither']['amp'])
        #self.ui.seedFutureSpin.setValue(self.joint_config['future_time'])

    def commit_values(self):
        if (
                self.controller.leg is None or
                not hasattr(self.controller.leg, 'mgr')):
            return
        # compare to joint config
        # set ui elements by joint_config
        values = {
            'pid': {}, 'pwm': {}, 'adc': {}, 'dither': {}}
        values['pid']['p'] = self.ui.pidPSpin.value()
        values['pid']['i'] = self.ui.pidISpin.value()
        values['pid']['d'] = self.ui.pidDSpin.value()
        values['pid']['min'] = self.ui.pidMinSpin.value()
        values['pid']['max'] = self.ui.pidMaxSpin.value()
        values['following_error_threshold'] = \
            self.ui.pidErrorThresholdSpin.value()
        values['pwm']['extend_min'] = self.ui.extendMinSpin.value()
        values['pwm']['extend_max'] = self.ui.extendMaxSpin.value()
        values['pwm']['retract_min'] = self.ui.retractMinSpin.value()
        values['pwm']['retract_max'] = self.ui.retractMaxSpin.value()
        values['adc']['min'] = self.ui.adcLimitMinSpin.value()
        values['adc']['max'] = self.ui.adcLimitMaxSpin.value()
        values['dither']['time'] = self.ui.ditherTimeSpin.value()
        values['dither']['amp'] = self.ui.ditherAmpSpin.value()
        #values['future_time'] = self.ui.seedFutureSpin.value()

        txt = str(self.ui.pidJointCombo.currentText())
        try:
            index = ['Hip', 'Thigh', 'Knee'].index(txt)
        except ValueError:
            return

        v = values['pid']
        j = self.joint_config['pid']
        if (
                v['p'] != j['p'] or v['i'] != j['i'] or v['d'] != j['i']):
            args = (
                index,
                values['pid']['p'], values['pid']['i'], values['pid']['d'],
                values['pid']['min'], values['pid']['max'])
            # print("pid_config", args)
            log.info({'pid_config': args})
            self.controller.leg.mgr.trigger('pid_config', *args)

        v = values['following_error_threshold']
        j = self.joint_config['following_error_threshold']
        if (v != j):
            self.ui.pidErrorThresholdSpin.setValue(
                self.joint_config['following_error_threshold'])
            args = (index, float(v))
            log.info({'following_error_threshold': args})
            self.controller.leg.mgr.trigger(
                'following_error_threshold', *args)

        v = values['pwm']
        j = self.joint_config['pwm']
        if (
                v['extend_min'] != j['extend_min'] or
                v['extend_max'] != j['extend_max'] or
                v['retract_min'] != j['retract_min'] or
                v['retract_max'] != j['retract_max']):
            args = (
                index,
                int(values['pwm']['extend_min']),
                int(values['pwm']['extend_max']),
                int(values['pwm']['retract_min']),
                int(values['pwm']['retract_max']))
            # print("pwm_limits:", args)
            log.info({'pwm_limits': args})
            self.controller.leg.mgr.trigger('pwm_limits', *args)
        v = values['adc']
        j = self.joint_config['adc']
        if (v['min'] != j['min'] or v['max'] != j['max']):
            args = (index, values['adc']['min'], values['adc']['max'])
            # print("adc_limits:", args)
            log.info({'adc_limits': args})
            self.controller.leg.mgr.trigger('adc_limits', *args)
        v = values['dither']
        #j = self.joint_config['dither']
        if (v['time'] != j['time'] or v['amp'] != j['amp']):
            args = (
                #index, int(values['dither']['time']),
                int(values['dither']['time']),
                int(values['dither']['amp']))
            # print("dither:", args)
            log.info({'dither': args})
            self.controller.leg.mgr.trigger('dither', *args)
        #v = values['future_time']
        #j = self.joint_config['future_time']
        #if (v != j):
        #    args = (int(v), )
        #    log.info({'pid_future_time': args})
        #    self.controller.leg.mgr.trigger('pid_future_time', *args)
        self.read_joint_config()

    def clear_pid_values(self):
        self.chart.clearData()
        self.chart.update()

    def timer_update(self):
        rd = list(numpy.random.random(3))
        self.add_pid_values(*rd)

    def start_showing(self):
        self.clear_pid_values()
        if self.controller is None:
            print("starting timer")
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self.timer_update)
            self.timer.start(50)

    def stop_showing(self):
        if self.controller is None:
            self.timer.stop()


class LegTab(Tab):
    views = {
        'side': {
            'azimuth': numpy.pi,
            'elevation': numpy.pi / 2,
            'offset': (-200, 0),
            'scalar': 3.,
        },
        'top': {
            'azimuth': 0,
            'elevation': 0,
            'offset': (-200, 0),
            'scalar': 3.,
        },
    }

    def __init__(self, ui, controller):
        self.display = ui.legDisplay
        super(LegTab, self).__init__(ui, controller)
        self.set_view('side')

    def set_leg_index(self, index):
        if self.controller is None:
            return
        if self._last_leg_index is not None:
            self.controller.legs[self._last_leg_index].remove_on(
                'angles', self.on_angles)
            self.controller.legs[self._last_leg_index].remove_on(
                'xyz', self.on_xyz)
            self.controller.legs[self._last_leg_index].remove_on(
                'adc', self.on_adc)
            self.controller.res.feet[self._last_leg_index].remove_on(
                'restriction', self.on_restriction)
        super(LegTab, self).set_leg_index(index)  # update index
        self.display.leg.number = index
        self.display.update()
        if index is not None:
            self.controller.leg.on(
                'angles', self.on_angles)
            self.controller.leg.on(
                'xyz', self.on_xyz)
            self.controller.leg.on(
                'adc', self.on_adc)
            self.controller.res.feet[self._last_leg_index].on(
                'restriction', self.on_restriction)

    def set_view(self, view):
        if not isinstance(view, dict):
            view = self.views[view]
        for k in view:
            setattr(self.display.projection, k, view[k])
        self.display.update()

    def plot_leg(self, hip, thigh, knee):
        self.display.leg.set_angles(hip, thigh, knee)
        self.display.update()
        return

    def update_timer(self):
        self.plot_leg(self.angles[0], self.angles[1], self.angles[2])
        for i in xrange(3):
            self.angles[i] += self.deltas[i]
            if (
                    self.angles[i] > self.limits[i][0] or
                    self.angles[i] < self.limits[i][1]):
                self.deltas[i] *= -1

    def on_angles(self, angles):
        # TODO what to do when v is False?
        self.plot_leg(angles['hip'], angles['thigh'], angles['knee'])
        self.ui.legLLineEdit.setText('%0.2f' % angles['calf'])

    def on_xyz(self, xyz):
        self.ui.legXLineEdit.setText('%0.2f' % xyz['x'])
        self.ui.legYLineEdit.setText('%0.2f' % xyz['y'])
        self.ui.legZLineEdit.setText('%0.2f' % xyz['z'])

    def on_restriction(self, r):
        self.ui.legRLineEdit.setText('%0.2f' % r['r'])

    def on_adc(self, adc):
        self.ui.hipADCProgress.setValue(adc['hip'])
        self.ui.thighADCProgress.setValue(adc['thigh'])
        self.ui.kneeADCProgress.setValue(adc['knee'])
        self.ui.calfADCProgress.setValue(adc['calf'])

    def start_showing(self):
        if self.controller is None:
            self.angles = [0., 0., 0.]
            self.deltas = [0.01, 0.01, -0.02]
            self.limits = [[0.6, -0.6], [1.1, 0.], [0., -1.1]]
            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self.update_timer)
            self.timer.start(50)

    def stop_showing(self):
        if self.controller is None:
            self.timer.stop()


class BodyTab(Tab):
    views = {
        'back': {
            'azimuth': numpy.pi,
            'elevation': numpy.pi / 2.,
            'offset': (0, 0),
            'scalar': 1.,
        },
        'top': {
            'azimuth': numpy.pi,
            'elevation': 0,
            'offset': (0, 0),
            'scalar': 1.,
        },
    }

    def __init__(self, ui, controller):
        self.display = ui.bodyDisplay
        super(BodyTab, self).__init__(ui, controller)
        self.heightLabel = ui.heightLabel

        # attach to all legs
        #self.controller.legs[i]
        self.controller.on('height', self.on_height)
        self.controller.on('mode', self.on_mode)
        for leg_number in self.controller.legs:
            self.display.add_leg(leg_number)
            self.controller.legs[leg_number].on(
                'angles', lambda a, i=leg_number: self.on_angles(a, i))
            self.controller.legs[leg_number].on(
                'xyz', lambda a, i=leg_number: self.on_xyz(a, i))
            self.controller.res.feet[leg_number].on(
                'restriction',
                lambda a, i=leg_number: self.on_restriction(a, i))
            self.controller.res.feet[leg_number].on(
                'state',
                lambda a, i=leg_number: self.on_res_state(a, i))
        #self.show_top_view()
        self.set_view('top')
        self.controller.on('config_updated', self.set_config_values)
        self.set_config_values()
        ui.configTree.resizeColumnToContents(0)

    def set_config_values(self, item=None):
        if item is None:
            item = self.ui.configTree.invisibleRootItem()
        if item.columnCount() == 2:
            parent = item.parent()
            if parent is not None:
                parent = str(parent.text(0))
            attr, value = str(item.text(0)), str(item.text(1))
            if parent is not None:
                attr = '.'.join((parent, attr))
            ts = attr.split('.')
            obj = self.controller
            assert ts[0] == 'controller'
            ts = ts[1:]
            while len(ts) > 1:
                obj = getattr(obj, ts.pop(0))
                if obj is None:
                    break
            if obj is not None:
                attr = ts[0]
                if isinstance(obj, dict):
                    old_value = obj[attr]
                else:
                    old_value = getattr(obj, attr)
                item.setText(1, str(old_value))
        for i in range(item.childCount()):
            self.set_config_values(item.child(i))
        if item == self.ui.configTree.invisibleRootItem():
            self.ui.configTree.resizeColumnToContents(0)

    def set_leg_index(self, index):
        if self.controller is None:
            return
        self.display.selected_leg = index
        super(BodyTab, self).set_leg_index(index)

    def set_view(self, view):
        if not isinstance(view, dict):
            view = self.views[view]
        for k in view:
            setattr(self.display.projection, k, view[k])
        self.display.update()

    def plot_leg(self, leg_number, hip, thigh, knee, calf):
        self.display.legs[leg_number].set_angles(hip, thigh, knee, calf)
        self.display.update()
        return

    def on_angles(self, angles, leg_number):
        self.plot_leg(
            leg_number, angles['hip'], angles['thigh'], angles['knee'],
            angles['calf'])

    def on_xyz(self, xyz, leg_number):
        pass

    def on_restriction(self, res, leg_number):
        self.display.legs[leg_number].restriction = res
        self.display.update()
        return

    def on_height(self, height):
        self.heightLabel.setText("Height: %0.2f" % height)

    def on_mode(self, mode):
        if mode == 'body_restriction':
            self._update_support_legs()
        else:
            self.display.support_legs = []

    def on_res_state(self, state, leg_number):
        self._update_support_legs()

    def _update_support_legs(self):
        # draw polygon between supported legs
        lns = sorted(self.controller.res.feet)
        support_legs = []
        for ln in lns:
            if self.controller.res.feet[ln].state in ('stance', 'wait'):
                support_legs.append(ln)
        if not len(support_legs):
            return
        self.display.support_legs = support_legs
        self.display.update()
        # TODO calculate pitch and roll


class TabManager(object):
    def __init__(self, tab_widget):
        self.tab_widget = tab_widget
        self.tab_widget.currentChanged.connect(self.tab_changed)
        self.tabs = {}
        self.current = None

    def show_current(self):
        i = self.tab_widget.currentIndex()
        if i == -1:
            return
        self.tab_changed(i)

    def add_tab(self, name, tab):
        self.tabs[name] = tab

    def tab_changed(self, index):
        # lookup index
        label = str(self.tab_widget.tabText(index))
        if self.current is not None:
            self.current.stop_showing()
            self.current = None
        if label in self.tabs:
            self.tabs[label].start_showing()
            self.current = self.tabs[label]


def load_ui(controller=None):
    app = QtGui.QApplication(sys.argv)
    MainWindow = QtGui.QMainWindow()
    ui = base.Ui_MainWindow()
    ui.setupUi(MainWindow)
    # setup menus
    ui._calibrationMenu_actions = []
    a = QtGui.QAction("Save", ui.calibrationMenu)
    a.triggered.connect(lambda a: calibration.save_calibrations())
    ui._calibrationMenu_actions.append(a)
    ui.calibrationMenu.addAction(a)
    if controller is not None:
        a = QtGui.QAction("Zero calf", ui.calibrationMenu)
        a.triggered.connect(lambda a: controller.leg.compute_calf_zero())
        ui._calibrationMenu_actions.append(a)
        ui.calibrationMenu.addAction(a)

        ui._legsMenu_actions = []
        for leg in controller.legs:
            a = QtGui.QAction(
                consts.LEG_NAME_BY_NUMBER[leg], ui.legsMenu)
            a.triggered.connect(lambda a, i=leg: controller.set_leg(i))
            ui._legsMenu_actions.append(a)
            ui.legsMenu.addAction(a)
        ui._modesMenu_actions = []
        for mode in controller.modes:
            a = QtGui.QAction(mode, ui.modesMenu)
            a.triggered.connect(lambda a, m=mode: controller.set_mode(m))
            ui._modesMenu_actions.append(a)
            ui.modesMenu.addAction(a)
        ui.modeLabel.setText("Mode: %s" % controller.mode)
        ui.legLabel.setText(
            "Leg: %s" % consts.LEG_NAME_BY_NUMBER[controller.leg_index])
        controller.on('mode', lambda m: ui.modeLabel.setText("Mode: %s" % m))
        controller.on('set_leg', lambda m: ui.legLabel.setText(
            "Leg: %s" % consts.LEG_NAME_BY_NUMBER[m]))
        controller.on('estop', lambda v: (
            ui.estopLabel.setText(
                "Estop: %s" % consts.ESTOP_BY_NUMBER[v]),
            ui.estopLabel.setStyleSheet((
                "background-color: green;" if v == consts.ESTOP_OFF else
                "background-color: none;"))
        ))
    tm = TabManager(ui.tabs)
    tm.add_tab('PID', PIDTab(ui, controller))
    tm.add_tab('Leg', LegTab(ui, controller))
    tm.add_tab('Body', BodyTab(ui, controller))
    tm.show_current()

    if 'imu' in controller.bodies:
        controller.bodies['imu'].on(
            'feed_pressure', lambda v: ui.pressureLabel.setText("PSI: %i" % v))
        controller.bodies['imu'].on(
            'engine_rpm', lambda v: ui.rpmLabel.setText("RPM: %0.0f" % v))
        controller.bodies['imu'].on(
            'feed_oil_temp',
            lambda v: ui.oilTempLabel.setText("Temp: %0.2f" % v))
        controller.bodies['imu'].on(
            'heading',
            lambda r, p, y: ui.imuLabel.setText(
                "IMU: %0.2f %0.2f %0.2f" % (r, p, y)))

    # update tree widget to show values from python
    #set_values(ui.configTree.invisibleRootItem())
    #tm.tabs['Body'].set_config_values()
    #ui.configTree.resizeColumnToContents(0)
    # listen for configTree changes

    def item_changed(item):
        # TODO recurse through parents
        parent = item.parent()
        if parent is not None:
            parent = str(parent.text(0))
        attr, value = str(item.text(0)), str(item.text(1))
        print(parent, attr, value)
        if parent is not None:
            attr = '.'.join((parent, attr))
        # get old value
        ts = attr.split('.')
        obj = controller
        assert ts[0] == 'controller'
        ts = ts[1:]
        while len(ts) > 1:
            obj = getattr(obj, ts.pop(0))
        attr = ts[0]
        if isinstance(obj, dict):
            old_value = obj[attr]
        else:
            old_value = getattr(obj, attr)
        print("Old value: %s" % old_value)
        try:
            value = type(old_value)(value)
        except Exception as e:
            print("Error converting value %s: %s [%s]" % (attr, value, e))
            item.setText(1, str(old_value))
            return
        try:
            if isinstance(obj, dict):
                obj[attr] = value
            else:
                setattr(obj, attr, value)
        except Exception as e:
            print("Error setting config %s = %s [%s]" % (attr, value, e))
            item.setText(1, str(old_value))
            return

    ui.configTree.itemChanged.connect(item_changed)
    MainWindow.show()
    timer = None
    if controller is not None:
        timer = QtCore.QTimer()

        def update():
            try:
                controller.update()
            except Exception as e:
                ex_type, ex, tb = sys.exc_info()
                print("controller update error: %s" % e)
                traceback.print_tb(tb)
                # TODO stop updates on error?
                #timer.stop()
        #timer.timeout.connect(controller.update)
        timer.timeout.connect(update)
        timer.start(10)
    return {
        'app': app, 'ui': ui, 'window': MainWindow, 'tab_manager': tm,
        'timer': timer}


def run_ui(ui):
    sys.exit(ui['app'].exec_())


def start():
    if joystick.ps3.available():
        joy = joystick.ps3.PS3Joystick()
    elif joystick.steel.available():
        joy = joystick.steel.SteelJoystick()
        print("Connected to steel joystick")
    else:
        joy = None

    legs = leg.teensy.connect_to_teensies()

    if len(legs) == 0:
        raise IOError("No teensies found")

    lns = sorted(legs.keys())
    print("Connected to legs: %s" % (lns, ))

    bodies = body.connect_to_teensies()
    print("Connected to bodies: %s" % (sorted(bodies.keys())))

    c = controllers.multileg.MultiLeg(legs, joy, bodies)

    run_ui(load_ui(c))


if __name__ == "__main__":
    ui = load_ui()
    run_ui(ui)
