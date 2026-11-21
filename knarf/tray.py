"""The tray icon: a StatusNotifierItem with a dbusmenu, shown in waybar's tray like other apps."""

import math
import os

import numpy as np

from .config import COLORS
from .gtk import Gio, GLib, cairo


SNI_XML = """<node>
<interface name="org.kde.StatusNotifierItem">
  <property name="Category" type="s" access="read"/>
  <property name="Id" type="s" access="read"/>
  <property name="Title" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="WindowId" type="i" access="read"/>
  <property name="IconName" type="s" access="read"/>
  <property name="IconPixmap" type="a(iiay)" access="read"/>
  <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
  <property name="ItemIsMenu" type="b" access="read"/>
  <property name="Menu" type="o" access="read"/>
  <method name="Activate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
  <method name="SecondaryActivate"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
  <method name="ContextMenu"><arg name="x" type="i" direction="in"/><arg name="y" type="i" direction="in"/></method>
  <method name="Scroll"><arg name="delta" type="i" direction="in"/><arg name="orientation" type="s" direction="in"/></method>
  <signal name="NewIcon"/>
  <signal name="NewToolTip"/>
  <signal name="NewStatus"><arg name="status" type="s"/></signal>
</interface>
</node>"""

MENU_XML = """<node>
<interface name="com.canonical.dbusmenu">
  <method name="GetLayout">
    <arg type="i" name="parentId" direction="in"/><arg type="i" name="recursionDepth" direction="in"/>
    <arg type="as" name="propertyNames" direction="in"/>
    <arg type="u" name="revision" direction="out"/><arg type="(ia{sv}av)" name="layout" direction="out"/>
  </method>
  <method name="GetGroupProperties">
    <arg type="ai" name="ids" direction="in"/><arg type="as" name="propertyNames" direction="in"/>
    <arg type="a(ia{sv})" name="properties" direction="out"/>
  </method>
  <method name="GetProperty">
    <arg type="i" name="id" direction="in"/><arg type="s" name="name" direction="in"/>
    <arg type="v" name="value" direction="out"/>
  </method>
  <method name="Event">
    <arg type="i" name="id" direction="in"/><arg type="s" name="eventId" direction="in"/>
    <arg type="v" name="data" direction="in"/><arg type="u" name="timestamp" direction="in"/>
  </method>
  <method name="EventGroup">
    <arg type="a(isvu)" name="events" direction="in"/><arg type="ai" name="idErrors" direction="out"/>
  </method>
  <method name="AboutToShow"><arg type="i" name="id" direction="in"/><arg type="b" name="needUpdate" direction="out"/></method>
  <method name="AboutToShowGroup">
    <arg type="ai" name="ids" direction="in"/>
    <arg type="ai" name="updatesNeeded" direction="out"/><arg type="ai" name="idErrors" direction="out"/>
  </method>
  <property name="Version" type="u" access="read"/>
  <property name="TextDirection" type="s" access="read"/>
  <property name="Status" type="s" access="read"/>
  <property name="IconThemePath" type="as" access="read"/>
  <signal name="LayoutUpdated"><arg type="u" name="revision"/><arg type="i" name="parent"/></signal>
  <signal name="ItemsPropertiesUpdated">
    <arg type="a(ia{sv})" name="updatedProps"/><arg type="a(ias)" name="removedProps"/>
  </signal>
</interface>
</node>"""

TRAY_TIPS = {"idle": "knarf is ready", "speaking": "knarf is speaking",
             "listening": "knarf is listening", "thinking": "knarf is transcribing"}


def tray_pixmaps(state, rgb):
    """Icon images for the tray, ARGB32 in network byte order, as the protocol wants."""
    out = []
    for size in (22, 32, 48):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surf)
        c = [v / 255 for v in rgb]
        r = size * 0.36
        if state == "listening":
            c = [1.0, 0.25, 0.2]  # mic is on: red, like a recording light
        elif state == "thinking":
            c = [1.0, 0.85, 0.1]
        if state in ("idle", "speaking"):
            if state == "speaking":
                cr.set_source_rgba(*c, 0.35)
                cr.arc(size / 2, size / 2, size * 0.48, 0, 2 * math.pi)
                cr.fill()
            cr.set_source_rgba(*c, 1)
            cr.arc(size / 2, size / 2, r, 0, 2 * math.pi)
            cr.fill()
        else:
            cr.set_source_rgba(*c, 1)
            cr.set_line_width(size * 0.13)
            cr.arc(size / 2, size / 2, r, 0, 2 * math.pi)
            cr.stroke()
        surf.flush()
        argb = np.frombuffer(surf.get_data(), dtype=np.uint32)[: size * size]
        out.append((size, size, argb.astype(">u4").tobytes()))
    return out


class Tray:
    """A StatusNotifierItem with a small menu. Callbacks run on the GTK main loop."""

    PATH, MENU_PATH = "/StatusNotifierItem", "/MenuBar"
    ITEMS = [  # (id, label); label None = separator
        (1, "Show / hide circle"), (2, "Listen"), (3, "Stop speaking"), (4, None),
        (5, "Settings…"), (6, None), (8, "Restart knarf"), (7, "Quit knarf"),
    ]

    def __init__(self, circle):
        self.circle = circle
        self.state = "idle"
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        sni = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
        menu = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]
        self.bus.register_object(self.PATH, sni, self._sni_call, self._sni_prop, None)
        self.bus.register_object(self.MENU_PATH, menu, self._menu_call, self._menu_prop, None)
        Gio.bus_own_name_on_connection(self.bus, self.name, Gio.BusNameOwnerFlags.NONE, None, None)
        # (re-)register whenever a tray host appears, e.g. after waybar restarts
        Gio.bus_watch_name_on_connection(self.bus, "org.kde.StatusNotifierWatcher",
                                         Gio.BusNameWatcherFlags.NONE, self._watcher_up, None)

    def _watcher_up(self, bus, name, owner):
        bus.call("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                 "RegisterStatusNotifierItem", GLib.Variant("(s)", (self.name,)), None,
                 Gio.DBusCallFlags.NONE, -1, None, None)

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.refresh()

    def refresh(self):
        for sig in ("NewIcon", "NewToolTip"):
            self.bus.emit_signal(None, self.PATH, "org.kde.StatusNotifierItem", sig, None)

    def _sni_prop(self, bus, sender, path, iface, prop):
        rgb = COLORS[self.circle.st["color"]]
        pix = tray_pixmaps(self.state, rgb)
        return {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "knarf"),
            "Title": GLib.Variant("s", "knarf"),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("i", 0),
            "IconName": GLib.Variant("s", ""),
            "IconPixmap": GLib.Variant("a(iiay)", pix),
            "ToolTip": GLib.Variant("(sa(iiay)ss)", ("", [], "knarf", TRAY_TIPS[self.state])),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", self.MENU_PATH),
        }.get(prop)

    def _sni_call(self, bus, sender, path, iface, method, params, inv):
        if method == "Activate":
            self.circle.toggle_window()
        elif method == "SecondaryActivate":
            self.circle.ls.toggle()
        inv.return_value(None)

    def _menu_prop(self, bus, sender, path, iface, prop):
        return {"Version": GLib.Variant("u", 3), "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"), "IconThemePath": GLib.Variant("as", [])}.get(prop)

    def _item_props(self, label):
        if label is None:
            return {"type": GLib.Variant("s", "separator")}
        return {"label": GLib.Variant("s", label), "enabled": GLib.Variant("b", True),
                "visible": GLib.Variant("b", True)}

    def _menu_call(self, bus, sender, path, iface, method, params, inv):
        if method == "GetLayout":
            kids = [GLib.Variant("(ia{sv}av)", (i, self._item_props(lb), [])) for i, lb in self.ITEMS]
            root = (0, {"children-display": GLib.Variant("s", "submenu")}, kids)
            inv.return_value(GLib.Variant("(u(ia{sv}av))", (1, root)))
        elif method == "GetGroupProperties":
            ids = params.unpack()[0]
            props = [(i, self._item_props(lb)) for i, lb in self.ITEMS if not ids or i in ids]
            inv.return_value(GLib.Variant("(a(ia{sv}))", (props,)))
        elif method == "GetProperty":
            i, name = params.unpack()
            lb = dict(self.ITEMS).get(i)
            inv.return_value(GLib.Variant("(v)", (self._item_props(lb).get(name, GLib.Variant("s", "")),)))
        elif method == "Event":
            i, event = params.unpack()[:2]
            if event == "clicked":
                GLib.idle_add(self._menu_action, i)
            inv.return_value(None)
        elif method == "EventGroup":
            for i, event, _d, _t in params.unpack()[0]:
                if event == "clicked":
                    GLib.idle_add(self._menu_action, i)
            inv.return_value(GLib.Variant("(ai)", ([],)))
        elif method == "AboutToShow":
            inv.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            inv.return_value(GLib.Variant("(aiai)", ([], [])))
        else:
            inv.return_value(None)

    def _menu_action(self, i):
        c = self.circle
        {1: c.toggle_window, 2: c.ls.toggle, 3: c.sp.stop, 5: c.open_settings, 7: c.gapp.quit,
         8: c.restart}.get(i, lambda: None)()
        return False
