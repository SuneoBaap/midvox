"""Keep the local virtual desktop active without typing or network polling."""

import ctypes


class DesktopAwake:
    INTERVAL_SECONDS = 60

    def __init__(self, display=b":99"):
        self.display = display
        self.x11 = ctypes.CDLL("libX11.so.6")
        self.xtest = ctypes.CDLL("libXtst.so.6")
        pointer = ctypes.c_void_p
        integer = ctypes.c_int
        window = ctypes.c_ulong
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XOpenDisplay.restype = pointer
        self.x11.XDefaultRootWindow.argtypes = [pointer]
        self.x11.XDefaultRootWindow.restype = window
        self.x11.XQueryPointer.argtypes = [
            pointer, window, ctypes.POINTER(window), ctypes.POINTER(window),
            ctypes.POINTER(integer), ctypes.POINTER(integer),
            ctypes.POINTER(integer), ctypes.POINTER(integer),
            ctypes.POINTER(ctypes.c_uint),
        ]
        self.xtest.XTestFakeMotionEvent.argtypes = [
            pointer, integer, integer, integer, ctypes.c_ulong,
        ]
        self.x11.XFlush.argtypes = [pointer]
        self.x11.XCloseDisplay.argtypes = [pointer]

    def pulse(self):
        """Move one pixel and restore the pointer; reconnect X on each pulse."""
        display = self.x11.XOpenDisplay(self.display)
        if not display:
            return False
        try:
            root = self.x11.XDefaultRootWindow(display)
            root_return, child = ctypes.c_ulong(), ctypes.c_ulong()
            x, y, local_x, local_y = [ctypes.c_int() for _ in range(4)]
            mask = ctypes.c_uint()
            if not self.x11.XQueryPointer(
                display, root, ctypes.byref(root_return), ctypes.byref(child),
                ctypes.byref(x), ctypes.byref(y), ctypes.byref(local_x),
                ctypes.byref(local_y), ctypes.byref(mask),
            ):
                return False
            adjacent = x.value - 1 if x.value > 0 else 1
            moved = self.xtest.XTestFakeMotionEvent(display, -1, adjacent, y.value, 0)
            restored = self.xtest.XTestFakeMotionEvent(display, -1, x.value, y.value, 0)
            self.x11.XFlush(display)
            return bool(moved and restored)
        finally:
            self.x11.XCloseDisplay(display)
