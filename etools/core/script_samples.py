"""Bundled example Lua scripts (tutorials), seeded into the user scripts folder.

Samples are teaching material: each one documents the API it uses and a
realistic flow a user can copy.  Missing files are written on first open;
existing files are never overwritten unless ``force=True``.
"""

from __future__ import annotations

from etools.core import script_store

#: name -> source
SAMPLES: dict[str, str] = {
    "0_入门教程": (
        "-- ETools Lua 入门\n"
        "-- 本脚本演示最常用的 API。先在串口/烧录等页连接设备，再点「运行」。\n"
        "--\n"
        "-- 模块一览：\n"
        "--   etools.app     log / sleep / stopped / version\n"
        "--   etools.util    hex / unhex / checksum / append_checksum / verify_checksum\n"
        "--   etools.serial  send / send_hex / write / recv / expect\n"
        "--   etools.net     send / recv\n"
        "--   etools.term    send\n"
        "--   etools.flash   connected / erase_all / erase_range / program / read_mem / reset\n"
        "\n"
        "etools.app.log('hello from Lua')\n"
        "\n"
        "-- 编码示例：十六进制字符串 <-> 字节\n"
        "local raw = etools.util.unhex('48 65 6C 6C 6F')\n"
        "etools.app.log('bytes as hex: ' .. etools.util.hex(raw))\n"
        "\n"
        "-- 长循环里应检查 app.stopped()，方便用户随时中断\n"
        "for i = 1, 3 do\n"
        "  if etools.app.stopped() then\n"
        "    etools.app.log('stopped by user')\n"
        "    return\n"
        "  end\n"
        "  etools.app.log('tick ' .. i)\n"
        "  etools.app.sleep(200)\n"
        "end\n"
        "\n"
        "etools.app.log('tutorial done')\n"
    ),
    "1_定时发送": (
        "-- 定时发送教程\n"
        "-- 场景：设备每隔一段时间需要 AT 心跳。\n"
        "-- 前置：串口页已打开串口。\n"
        "--\n"
        "--   serial.send(text)  按当前发送格式/行尾/校验发送\n"
        "--   app.sleep(ms)      等待毫秒（不卡界面）\n"
        "\n"
        "local interval = 200\n"
        "local count = 5\n"
        "for i = 1, count do\n"
        "  etools.serial.send('AT')\n"
        "  etools.app.log('heartbeat #' .. i)\n"
        "  etools.app.sleep(interval)\n"
        "end\n"
        "etools.app.log('heartbeat finished')\n"
    ),
    "2_CRC校验": (
        "-- CRC / 校验教程\n"
        "-- 场景：给 Modbus 等二进制帧自动补校验，或核对帧尾。\n"
        "--\n"
        "--   util.unhex('01 03')            -> 字节\n"
        "--   util.hex(bytes)                -> '01 03'\n"
        "--   util.append_checksum(data, algo)\n"
        "--   util.verify_checksum(frame, algo)\n"
        "--   algo: xor sum8 sum16 crc8 crc16_modbus crc16_ccitt crc32\n"
        "\n"
        "local body = etools.util.unhex('01 03 00 00 00 01')\n"
        "local frame = etools.util.append_checksum(body, 'crc16_modbus')\n"
        "etools.app.log('body  ' .. etools.util.hex(body))\n"
        "etools.app.log('frame ' .. etools.util.hex(frame))\n"
        "assert(etools.util.verify_checksum(frame, 'crc16_modbus'))\n"
        "etools.app.log('verify OK')\n"
        "\n"
        "-- 串口已打开时发出整帧（发送格式选 HEX、行尾选「无」更干净）\n"
        "etools.serial.send_hex(etools.util.hex(frame))\n"
    ),
    "3_ASCII与HEX转换": (
        "-- ASCII / HEX 转换教程\n"
        "-- 场景：十六进制日志转可读文本，或把指令变成 HEX 发出。\n"
        "--\n"
        "--   util.unhex(str) -> 字节\n"
        "--   util.hex(bytes) -> 'AA BB CC'\n"
        "--   serial.recv(n)  -> 最多取 n 字节（不阻塞）\n"
        "\n"
        "local text_bytes = etools.util.unhex('48 65 6C 6C 6F 20 57 6F 72 6C 64')\n"
        "etools.app.log('hex dump: ' .. etools.util.hex(text_bytes))\n"
        "\n"
        "local chunk = etools.serial.recv(512)\n"
        "if chunk == '' then\n"
        "  etools.app.log('no data in buffer (open serial first)')\n"
        "else\n"
        "  etools.app.log('RX hex: ' .. etools.util.hex(chunk))\n"
        "end\n"
        "\n"
        "etools.serial.send_hex('AA 55 01 02')\n"
    ),
    "4_自动烧录流程": (
        "-- 自定义烧录流程教程\n"
        "-- 场景：固定「擦除 -> 烧录 -> 校验读回 -> 复位」产线步骤。\n"
        "-- 前置：烧录页已连接探针。\n"
        "--\n"
        "--   flash.connected()\n"
        "--   flash.erase_all() / flash.erase_range(addr, size)\n"
        "--   flash.program(path, verify)\n"
        "--   flash.read_mem(addr, size) -> hex 字符串\n"
        "--   flash.reset()\n"
        "\n"
        "if not etools.flash.connected() then\n"
        "  etools.app.log('请先在烧录页连接探针')\n"
        "  return\n"
        "end\n"
        "\n"
        "etools.app.log('step 1: erase')\n"
        "-- etools.flash.erase_all()\n"
        "etools.app.log('step 2: program')\n"
        "-- etools.flash.program('C:/work/app.elf', true)\n"
        "etools.app.log('step 3: read-back sample')\n"
        "-- etools.app.log(etools.flash.read_mem(0x08000000, 16))\n"
        "etools.app.log('step 4: reset')\n"
        "-- etools.flash.reset()\n"
        "etools.app.log('flash flow done (steps commented for safety)')\n"
    ),
    "5_串口问答": (
        "-- 串口问答教程（send + expect）\n"
        "-- 场景：AT 设备初始化，发命令并等待关键字。\n"
        "--\n"
        "--   serial.send(text)\n"
        "--   serial.expect(needle, timeout_ms) -> true/false\n"
        "\n"
        "etools.serial.send('AT+GMR')\n"
        "if etools.serial.expect('OK', 2000) then\n"
        "  etools.app.log('device ready')\n"
        "else\n"
        "  etools.app.log('timeout — check baud / wiring')\n"
        "end\n"
        "\n"
        "local cmds = { 'ATE0', 'AT+CMEE=2', 'AT+CGMR' }\n"
        "for _, c in ipairs(cmds) do\n"
        "  etools.serial.send(c)\n"
        "  etools.app.sleep(100)\n"
        "end\n"
    ),
    "6_网络与终端": (
        "-- 网络 / SSH 终端教程\n"
        "-- 场景：TCP 调试或远程执行命令（先在对应页建立连接）。\n"
        "--\n"
        "--   net.send(text) / net.recv(n)\n"
        "--   term.send(cmd)   在 SSH 终端执行一条命令\n"
        "\n"
        "etools.net.send('ping')\n"
        "local reply = etools.net.recv(256)\n"
        "if reply ~= '' then\n"
        "  etools.app.log('net rx: ' .. etools.util.hex(reply))\n"
        "end\n"
        "\n"
        "-- etools.term.send('uname -a')\n"
    ),
    "7_完整联调流水线": (
        "-- 完整联调流水线（串口）\n"
        "-- 综合：连通性检查 -> 配置 -> 循环上报（带 CRC）。\n"
        "-- 前置：串口已打开。\n"
        "\n"
        "etools.serial.send('AT')\n"
        "if not etools.serial.expect('OK', 1500) then\n"
        "  etools.app.log('device not responding')\n"
        "  return\n"
        "end\n"
        "\n"
        "etools.serial.send('AT+UART=115200,8,1,NONE')\n"
        "etools.app.sleep(200)\n"
        "\n"
        "for i = 1, 5 do\n"
        "  etools.serial.send('AT+READ?')\n"
        "  etools.app.sleep(300)\n"
        "  local body = etools.util.unhex(string.format('01 04 00 %02X', i))\n"
        "  local frame = etools.util.append_checksum(body, 'crc16_modbus')\n"
        "  etools.serial.send_hex(etools.util.hex(frame))\n"
        "  etools.app.log('frame ' .. i .. ' sent')\n"
        "end\n"
        "\n"
        "etools.app.log('pipeline done')\n"
    ),
}


def ensure_samples(force: bool = False) -> list[str]:
    """Write bundled tutorials into the user folder.

    Built-in samples are refreshed on open so tutorial text stays current;
    user-authored scripts with other names are left untouched.  Pass
    ``force=False`` and name a custom file to avoid overwriting that file.
    """
    written: list[str] = []
    for name, source in SAMPLES.items():
        try:
            current = script_store.load_script(name)
        except OSError:
            current = None
        if force or current is None or current != source:
            script_store.save_script(name, source)
            written.append(name)
    return written
