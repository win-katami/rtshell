#!/usr/bin/env python
# -*- Python -*-
# -*- coding: utf-8 -*-

'''rtshell

Copyright (C) 2009-2010
    Geoffrey Biggs
    RT-Synthesis Research Group
    Intelligent Systems Research Institute,
    National Institute of Advanced Industrial Science and Technology (AIST),
    Japan
    All rights reserved.
Licensed under the Eclipse Public License -v 1.0 (EPL)
http://www.opensource.org/licenses/eclipse-1.0.txt

Log recording and playing components used by rtlog

'''


import OpenRTM_aist
import RTC
import sys
import time
import traceback

import gen_comp
import ilog


###############################################################################
## Recorder component for rtlog

class Recorder(gen_comp.GenComp):
    def __init__(self, mgr, port_specs, logger_type=None, filename='',
            lims_are_ind=False, end=-1, verbose=False, *args, **kwargs):
        if lims_are_ind:
            max = end
            self._end = -1
        else:
            max = -1
            self._end = end
        try:
            del kwargs['max']
        except KeyError:
            pass
        gen_comp.GenComp.__init__(self, mgr, port_specs, max=max, *args,
                **kwargs)
        self._logger_type = logger_type
        self._fn = filename
        self._verb = verbose

    def onActivated(self, ec_id):
        start = time.time()
        # Add activated time to meta data
        # Add port specs to meta data (include names)
        meta = (start, self._port_specs)
        # Make file name from activated time
        if not self._fn:
            self._fn = 'rtlog_{0}.rtl'.format(int(start))
        # Create log, record meta data
        self._l = self._logger_type(filename=self._fn, mode='w', meta=meta, verbose=self._verb)
        return RTC.RTC_OK

    def onDeactivated(self, ec_id):
        # Finalise and close log
        self._l.close()
        return RTC.RTC_OK

    def _behv(self, ec_id):
        execed = 0
        result = RTC.RTC_OK
        for name in self._ports:
            p = self._ports[name]
            if p.port.isNew():
                execed += 1
                p.read()
                ts = self._log(p, name)
                if self._end > -1 and ts >= self._end:
                    # Reached the end time
                    self._set()
            if self._max > -1 and self._count >= self._max:
                # Reached the max entries
                return result, execed
        return result, execed

    def _log(self, port, port_name):
        if port.standard_type:
            ts = ilog.EntryTS(sec=port.data.tm.sec, nsec=port.data.tm.nsec)
        else:
            ts = ilog.EntryTS(time=time.time())
        self._l.write(ts, (port_name, port.data))
        return ts


###############################################################################
## Player component for rtlog

class Player(gen_comp.GenComp):
    def __init__(self, mgr, port_specs, logger_type=None, filename='',
            lims_are_ind=False, start=-1, end=-1, rate=1.0, abs_times=False,
            ignore_times=False, verbose=False, *args, **kwargs):
        if lims_are_ind:
            max = end
            self._end = -1
        else:
            max = -1
            self._end = end
        try:
            del kwargs['max']
        except KeyError:
            pass
        gen_comp.GenComp.__init__(self, mgr, port_specs, max=max, *args,
                **kwargs)
        self._logger_type = logger_type
        self._fn = filename
        self._start = start
        self._rate = rate
        self._abs = abs_times
        self._ig_times = ignore_times
        self._verb = verbose

    def onActivated(self, ec_id):
        try:
            self._l = self._logger_type(filename=self._fn, mode='r',
                    verbose=self._verb)
            # Read the metadata block
            start, log_port_specs = self._l.metadata
            self._vprint('Log started at {0}'.format(start))
            self._vprint('Log port specs are {0}'.format(
                [str(s) for s in log_port_specs]))
            self._offset = time.time() - start
            self._vprint('Time offset is {0}'.format(self._offset))

            # Check ports match
            for name in self._ports:
                matches = [s for s in log_port_specs if s.name == name]
                if len(matches) == 0:
                    print >>sys.stderr, 'WARNING: Port {0} not found in '\
                            'log.'.format(name)
                    continue
                elif len(matches) != 1:
                    print >>sys.stderr, 'WARNING: Port {0} occurs multiple '\
                            'times in the log.'.format(name)
                    continue
                m = matches[0]
                if m.type != self._ports[name].raw.type:
                    print >>sys.stderr, 'ERROR: Port {0} is incorrect data '\
                            'type; should be {1}.'.format(name,
                                    type(self._ports[name].data))
                    return RTC.RTC_ERROR

            # Fast-forward to the start time
        except:
            traceback.print_exc()
            return RTC.RTC_ERROR
        return RTC.RTC_OK

    def onDeactivated(self, ec_id):
        # Close log
        self._l.close()
        return RTC.RTC_OK

    def _behv(self, ec_id):
        execed = 0
        result = RTC.RTC_OK
        try:
            if self._ig_times:
                # Read self._rate items from the log and write them
                for ii in range(int(self._rate)):
                    self._vprint('Playing {0} entries.'.format(int(self._rate)))
                    if not self._pub_log_item():
                        print >>sys.stderr, '{0}: End of log reached.'.format(
                                sys.argv[0])
                        self._set()
                        result = RTC.RTC_ERROR
                    else:
                        execed += 1
            else:
                # Calculate the current time in log-time
                now = (time.time() - self._offset) * self._rate
                self._vprint('Current time in logspace is {0}'.format(now))
                # Read until past it - read one at a time to avoid huge memory
                # spikes if the log contains large-sized data
                while self._l.pos[1] <= now:
                    if self._max > -1 and execed >= self._max:
                        self._vprint(
                                'Reached maximum number of results to play.')
                        break
                    if self._end > -1 and self._l.pos[1] > self._end:
                        self._bprint('Reached end time (current position: '\
                                '{0}).'.format(self._l.pos))
                        break
                    if not self._pub_log_item():
                        print >>sys.stderr, '{0}: End of log reached.'.format(
                                sys.argv[0])
                        self._set()
                        result = RTC.RTC_ERROR
                        break
                    else:
                        execed += 1
        except:
            traceback.print_exc()
            return RTC.RTC_ERROR, 0
        return result, execed

    def _pub_log_item(self):
        # Read an item from the log file
        entries = self._l.read()
        if len(entries) == 0:
            return False # End of file
        index, ts, entry = entries[0]
        p_name, data = entry
        if p_name in self._ports:
            self._ports[p_name].port.write(data)
        return True

    def _vprint(self, text):
        if self._verb:
            print >>sys.stderr, text
