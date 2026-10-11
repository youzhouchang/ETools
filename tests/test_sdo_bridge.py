"""Lua SDO read waits for the response frame and returns the value."""

from etools.ui.tools.script_bridges import CanLuaBridge


def test_sdo_read_returns_expedited_value():
    class Pump:
        def submit(self, fn, timeout=30.0):
            return fn()

    class Page:
        def lua_sdo_read(self, node, index, sub):
            self.sent = (node, index, sub)
            return True

        def lua_take_sdo(self, node, index, sub):
            assert (node, index, sub) == (1, 0x1000, 0)
            return {"id": 0x581, "data": "4B 00 10 00 2A 00 00 00"}

    page = Page()
    text = CanLuaBridge(page, Pump()).sdo_read(1, 0x1000, 0)
    assert page.sent == (1, 0x1000, 0)
    assert text == "2A 00"
