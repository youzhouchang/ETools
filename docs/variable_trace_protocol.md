# ETools 变量数据流协议

变量监控的 RTT/SWO 模式由目标固件主动发送采样值。主机不再通过 SWD 读取变量，因此采样频率主要由固件、RTT 缓冲区或 SWO 时钟决定。RTT 和 SWO 使用同一套字节帧。

每个帧使用小端序：

```text
4 bytes  magic = "EVM1"
1 byte   version = 1
1 byte   flags（保留，写 0）
2 bytes  payload_length
payload  repeated records
```

每条记录为：

```text
4 bytes  variable address（ELF 链接地址）
1 byte   type: 1=signed integer, 2=unsigned integer, 3=float32, 4=float64
1 byte   value size（整数 1~8，float32 为 4，float64 为 8）
N bytes  value
```

例如，向 RTT 上行通道或 SWO ITM 端口发送一个 32 位浮点数：

```c
// address 是链接器生成的变量地址，value 按小端序写入。
static const uint8_t frame[] = {
    'E', 'V', 'M', '1', 1, 0,
    10, 0,                         // payload length
    0x00, 0x00, 0x00, 0x20,       // address = 0x20000000
    3, 4,                          // float32, 4 bytes
    0x00, 0x00, 0x80, 0x3f        // value = 1.0f
};
```

实际项目中建议把多条记录合并到一个帧里，并使用固定大小的 RTT 上行缓冲区。主机端按 ELF 中的变量地址匹配记录；变量名和类型来自 ELF/DWARF，数据流中的类型字段用于校验和解码。
