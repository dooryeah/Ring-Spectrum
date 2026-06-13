import ctypes
from ctypes import wintypes

import numpy as np
import pygame
import win32api
import win32con
import win32gui


AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
ULW_ALPHA = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class SIZE(ctypes.Structure):
    _fields_ = [
        ("cx", wintypes.LONG),
        ("cy", wintypes.LONG),
    ]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HANDLE


class LayeredWindowBitmap:
    def __init__(self):
        self.width = 0
        self.height = 0
        self.mem_dc = None
        self.bitmap = None
        self.old_bitmap = None
        self.bits = None
        self.bgra = None
        self.alpha_buffer = None
        self.channel_buffer = None

    def close(self):
        if self.mem_dc and self.old_bitmap:
            gdi32.SelectObject(self.mem_dc, self.old_bitmap)
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
        if self.mem_dc:
            gdi32.DeleteDC(self.mem_dc)
        self.width = 0
        self.height = 0
        self.mem_dc = None
        self.bitmap = None
        self.old_bitmap = None
        self.bits = None
        self.bgra = None
        self.alpha_buffer = None
        self.channel_buffer = None

    def ensure_size(self, width, height):
        if self.width == width and self.height == height and self.mem_dc and self.bitmap:
            return

        self.close()
        screen_dc = user32.GetDC(None)
        try:
            self.mem_dc = gdi32.CreateCompatibleDC(screen_dc)
            if not self.mem_dc:
                raise ctypes.WinError()

            bitmap_info = BITMAPINFO()
            bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bitmap_info.bmiHeader.biWidth = width
            bitmap_info.bmiHeader.biHeight = -height
            bitmap_info.bmiHeader.biPlanes = 1
            bitmap_info.bmiHeader.biBitCount = 32
            bitmap_info.bmiHeader.biCompression = BI_RGB
            bitmap_info.bmiHeader.biSizeImage = width * height * 4

            bits = ctypes.c_void_p()
            self.bitmap = gdi32.CreateDIBSection(
                self.mem_dc,
                ctypes.byref(bitmap_info),
                DIB_RGB_COLORS,
                ctypes.byref(bits),
                None,
                0,
            )
            if not self.bitmap or not bits.value:
                raise ctypes.WinError()

            self.old_bitmap = gdi32.SelectObject(self.mem_dc, self.bitmap)
            self.bits = bits
            self.width = width
            self.height = height
            self.bgra = np.empty((height, width, 4), dtype=np.uint8)
            self.alpha_buffer = np.empty((height, width), dtype=np.uint16)
            self.channel_buffer = np.empty((height, width), dtype=np.uint16)
        finally:
            user32.ReleaseDC(None, screen_dc)

    def update(self, hwnd, surface, x, y, alpha_mask=None, color_mask=None):
        width, height = surface.get_size()
        self.ensure_size(width, height)

        rgb = pygame.surfarray.pixels3d(surface)
        alpha = pygame.surfarray.pixels_alpha(surface)
        try:
            alpha_src = alpha.T
            if alpha_mask is not None:
                np.multiply(alpha_src, alpha_mask, out=self.alpha_buffer, casting="unsafe")
                np.floor_divide(self.alpha_buffer, 255, out=self.alpha_buffer)
            else:
                np.copyto(self.alpha_buffer, alpha_src, casting="unsafe")

            np.copyto(self.bgra[:, :, 3], self.alpha_buffer, casting="unsafe")
            for dst_channel, src_channel in ((0, 2), (1, 1), (2, 0)):
                if color_mask is not None:
                    np.multiply(
                        color_mask[:, :, src_channel],
                        self.alpha_buffer,
                        out=self.channel_buffer,
                        casting="unsafe",
                    )
                else:
                    np.multiply(rgb[:, :, src_channel].T, self.alpha_buffer, out=self.channel_buffer, casting="unsafe")
                np.floor_divide(self.channel_buffer, 255, out=self.channel_buffer)
                np.copyto(self.bgra[:, :, dst_channel], self.channel_buffer, casting="unsafe")
        finally:
            del alpha
            del rgb

        ctypes.memmove(self.bits.value, self.bgra.ctypes.data, self.bgra.nbytes)

        screen_dc = user32.GetDC(None)
        try:
            dst_point = POINT(int(x), int(y))
            size = SIZE(width, height)
            src_point = POINT(0, 0)
            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            updated = user32.UpdateLayeredWindow(
                hwnd,
                screen_dc,
                ctypes.byref(dst_point),
                ctypes.byref(size),
                self.mem_dc,
                ctypes.byref(src_point),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            )
            if not updated:
                raise ctypes.WinError()
        finally:
            user32.ReleaseDC(None, screen_dc)


def apply_window_ex_style(hwnd, ex_style):
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    win32gui.SetWindowPos(
        hwnd,
        0,
        0,
        0,
        0,
        0,
        win32con.SWP_NOMOVE
        | win32con.SWP_NOSIZE
        | win32con.SWP_NOZORDER
        | win32con.SWP_NOACTIVATE
        | win32con.SWP_FRAMECHANGED,
    )


def show_window_no_activate(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)


def set_window_layering(hwnd, use_per_pixel_alpha, alpha_percent, color_key, hide_during_reset=False):
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    base_style = (ex_style | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TRANSPARENT) & ~win32con.WS_EX_TOPMOST
    layered_style = base_style | win32con.WS_EX_LAYERED
    hidden_for_reset = False

    if use_per_pixel_alpha and (ex_style & win32con.WS_EX_LAYERED):
        if hide_during_reset:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            hidden_for_reset = True
        apply_window_ex_style(hwnd, base_style & ~win32con.WS_EX_LAYERED)

    apply_window_ex_style(hwnd, layered_style)
    if not use_per_pixel_alpha:
        win32gui.SetLayeredWindowAttributes(
            hwnd,
            win32api.RGB(*color_key),
            int(255 * max(0, min(100, int(alpha_percent))) / 100),
            win32con.LWA_COLORKEY | win32con.LWA_ALPHA,
        )
    return hidden_for_reset


def update_window_pos(hwnd, x, y, width, height):
    x = int(x)
    y = int(y)
    width = int(width)
    height = int(height)
    win32gui.SetWindowPos(
        hwnd,
        0,
        x,
        y,
        width,
        height,
        win32con.SWP_SHOWWINDOW | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
    )
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        if (left, top, right - left, bottom - top) != (x, y, width, height):
            win32gui.MoveWindow(hwnd, x, y, width, height, True)
    except Exception:
        pass


def get_overlay_options(settings_title):
    opts = ["【默认】桌面底层", "【全局】始终置顶"]

    def enum_win(h, ctx):
        if win32gui.IsWindowVisible(h):
            title = win32gui.GetWindowText(h)
            if title and title not in ["Program Manager", settings_title]:
                opts.append(title)

    win32gui.EnumWindows(enum_win, None)
    seen = set()
    return [option for option in opts if not (option in seen or seen.add(option))]
