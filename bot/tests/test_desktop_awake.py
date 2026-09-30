"""Native keep-awake restores the pointer and survives missing displays."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from desktop_awake import DesktopAwake


class DesktopAwakeTests(unittest.TestCase):
    def make_awake(self, x=100, y=200):
        x11, xtest = MagicMock(), MagicMock()
        x11.XOpenDisplay.return_value = 123

        def query(*args):
            args[4]._obj.value = x
            args[5]._obj.value = y
            return 1

        x11.XQueryPointer.side_effect = query
        xtest.XTestFakeMotionEvent.return_value = 1
        with patch("desktop_awake.ctypes.CDLL", side_effect=[x11, xtest]):
            awake = DesktopAwake()
        return awake, x11, xtest

    def test_pointer_is_restored_and_connection_closed(self):
        awake, x11, xtest = self.make_awake()
        self.assertTrue(awake.pulse())
        self.assertEqual(
            [call.args for call in xtest.XTestFakeMotionEvent.call_args_list],
            [(123, -1, 99, 200, 0), (123, -1, 100, 200, 0)],
        )
        x11.XCloseDisplay.assert_called_once_with(123)

    def test_left_edge_moves_inside_display_then_restores(self):
        awake, _, xtest = self.make_awake(x=0)
        self.assertTrue(awake.pulse())
        self.assertEqual(xtest.XTestFakeMotionEvent.call_args_list[0].args[2], 1)
        self.assertEqual(xtest.XTestFakeMotionEvent.call_args_list[1].args[2], 0)

    def test_missing_or_unqueryable_display_never_moves_pointer(self):
        awake, x11, xtest = self.make_awake()
        x11.XOpenDisplay.return_value = None
        self.assertFalse(awake.pulse())
        xtest.XTestFakeMotionEvent.assert_not_called()
        x11.XOpenDisplay.return_value = 456
        x11.XQueryPointer.side_effect = None
        x11.XQueryPointer.return_value = 0
        self.assertFalse(awake.pulse())
        xtest.XTestFakeMotionEvent.assert_not_called()
        x11.XCloseDisplay.assert_called_once_with(456)
