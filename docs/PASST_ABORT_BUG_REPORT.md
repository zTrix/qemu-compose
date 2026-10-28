# qemu-compose passt 用户网络导致 QEMU SIGABRT —— bug 修复报告

- 报告日期：2026-10-28
- 状态：已定位，待修复
- 严重级别：高（VM 无预警退出，长跑任务/交互会话直接丢失）
- 主责仓库：`/home/ztx/prj/qemu-compose`
- 触发配置：`/home/ztx/prj/knowall/qemu-compose.yml`（`name: knowall`）
- 受影响实例：`9e3a0f1ff8074e9dbc3357f86b6e4024`（knowall，已退出）
- 同类风险实例：`d43ed86caa90439bbf9b668cadae7945`（bb，running）、`be17e9144bd24906a12efc6223784886`（ctf-challs，running）

---

## 0. 给接手的 agent 的 TL;DR

> 接手指令：先按第 8 节方案 A 实施并跑第 10 节验收，**不要**先做 vhost-user 或改系统 QEMU；
> 方案 A 合并、knowall 稳定运行后，再评估方案 B。

1. **不是宿主 OOM，也不是 guest 关机**。两次都是 QEMU 自己触发断言后 `SIGABRT`。
2. **触发路径**：qemu-compose 从 2026-10-24 起默认使用 passt，通过
   `-netdev socket,id=user.qemu-compose,fd=N` 把 passt 接到 QEMU。这个 netdev 走
   QEMU 的 `net/socket.c`。
3. **QEMU 的 bug**：`net_socket_send()` 在 `recv()` 返回 `EAGAIN/EWOULDBLOCK` 时没有
   return，继续把 `size == -1` 传给 `net_fill_rstate()`，后者末尾
   `assert(size == 0)` 失败 → abort。`net/stream_data.c` 有完全相同的 bug。
   上游 issue #3285，QEMU 10.2.0 报告，11.1.2 仍未修。
4. **修复方向**：
   - 立即方案（推荐先做）：给 qemu-compose 加 passt 开关（env / config），允许回退到
     QEMU 自带 slirp。slirp 不走 `net/socket.c`，不会再触发该断言。
   - 长期方案（保留 passt 性能）：改用 passt 的 **vhost-user** 模式，绕过
     `net/stream_data.c`。注意 QEMU 自带的 `-netdev passt` **默认 stream 模式仍然有同一个
     bug**，不能用默认模式。
5. **不要做的事**：不要 `qemu-compose down/rm` knowall（会删实例/磁盘）；不要删除
   `~/.local/share/qemu-compose/instance/9e3a0f1ff807.../disk.qcow2`；不要直接切到
   QEMU 默认 `-netdev passt`（同 bug）。

---

## 1. 结论

qemu-compose 的 passt 用户网络集成使用了 QEMU 的 stream socket netdev
（`-netdev socket,...,fd=N`）。QEMU 11.1.2 的 `net/socket.c` 在非阻塞 socket 上遇到
`EAGAIN` 时存在错误处理缺陷，会把 `-1` 当作读取长度继续解析，最终触发
`net_fill_rstate: Assertion 'size == 0' failed`，进程被 `SIGABRT` 杀死。
这是 QEMU 上游的已知 bug；qemu-compose 的 passt 集成让它变成了高概率、长跑必现的
稳定性问题。

---

## 2. 影响

- knowall 在 2026-10-27 和 2026-10-28 各崩溃一次，两次堆栈完全一致。
- 崩溃时 QEMU 直接 abort，没有走 guest 关机流程，也没有执行 after_script；
  guest 文件系统可能处于脏状态（qcow2 本身是崩溃一致的，重启后 systemd 会 fsck）。
- 所有在 2026-10-24 之后启动、且启用了 passt 的 VM 都受影响。当前仍在运行的
  `bb`、`ctf-challs` 随时可能以同样方式退出。
- 与 guest 内负载无关：knowall 第二次崩溃前 guest 控制台已经空闲约 20 小时，
  只要宿主侧有网络事件就可能触发。

---

## 3. 环境

| 项 | 值 |
|---|---|
| 宿主 | furnace |
| 内核 | `Linux 6.18.58-1-lts` |
| QEMU | `qemu-system-x86 11.1.2-1`（`-netdev help` 含 `passt`、`stream`、`socket`、`vhost-user`） |
| passt | `2026_10_02.cba3570-1`（`/usr/bin/passt`） |
| qemu-compose | v1.1.3，安装于 `/usr/lib/python3.14/site-packages/qemu_compose` |
| 仓库 HEAD | `e9180285b01d50e39eabf54d4e8ad8bad2fec6c5`（2026-10-25 Merge PR #42） |
| Python / uv | Python 3.14 / uv 0.13.5 |
| 宿主内存 | 62 GiB total，41 GiB available（无 OOM） |
| 根分区 | `/` 90% used（13G avail），`/var/lib/systemd/coredump` 约 5.6G |

已确认：安装到 site-packages 的 `qemu_runner.py` 与仓库当前版本**无差异**：

```bash
diff -u /usr/lib/python3.14/site-packages/qemu_compose/instance/qemu_runner.py \
        /home/ztx/prj/qemu-compose/qemu_compose/instance/qemu_runner.py
# 无输出
```

所以修复仓库后必须重新 build + install 才会生效。

---

## 4. 事故时间线

| 时间（CST） | 事件 |
|---|---|
| 2026-10-24 00:35–01:02 | qemu-compose 连续提交 `24e3075`、`9a1eab5`、`2dcc899` 等，引入 passt 默认用户网络、QEMU stream netdev、socketpair fd 传递 |
| 2026-10-25 09:43 | 合并 PR #42 `use_passt_user_network` |
| 2026-10-25 09:44 | 本地构建并安装 v1.1.3（当前运行版本） |
| 2026-10-27 07:16:43 | **第一次崩溃**：knowall 实例 `9697ff1aeb3342938373ddfec17a2a12`，QEMU PID 8184，coredump 3G，同一断言 |
| 2026-10-27 15:06 | 新 knowall 实例 `9e3a0f1ff8074e9dbc3357f86b6e4024` 启动 |
| 2026-10-27 15:13 | guest 控制台最后一次交互，之后空闲 |
| 2026-10-28 11:01:57.836 | **第二次崩溃**：QEMU PID 228662，`journald` 记录 coredump（coredumpctl 记录的崩溃时间戳为 11:01:29，core 写盘完成于 11:01:57） |
| 2026-10-28 11:01:58 | qemu-compose 控制台 socket 收到 EOF（`SocketIO.recv -> b''`） |
| 2026-10-28 11:02:00 | passt 打印 `Client connection closed, exiting` 后退出 |
| 2026-10-28 21:4x | 本次诊断；`bb`、`ctf-challs` 仍在运行 |

第一次崩溃的实例目录已被删除，但 coredump 中的 QEMU 命令行和堆栈仍然可以确认是
同一个 knowall 配置、同一个故障点。

---

## 5. 证据

### 5.1 qemu-compose 日志

`~/.local/share/qemu-compose/instance/9e3a0f1ff8074e9dbc3357f86b6e4024/qemu-compose.log` 末尾：

```
[2026-10-28_11:01:58] SocketIO.recv(1024) -> b''
WARNING:qemu_compose.qemu.machine.machine:qemu received signal 6; command: "/usr/bin/qemu-system-x86_64 ..."
INFO:qemu-compose.instance.qemu_runner:vm.process_io_log = "qemu-system-x86_64: -mon chardev=mon,mode=control: warning: '-mon' is deprecated, use '-object' with 'monitor-hmp' or 'monitor-qmp' types instead\nqemu-system-x86_64: ../qemu-11.1.2/net/net.c:2175: net_fill_rstate: Assertion `size == 0' failed.\n"
```

关键 QEMU 参数（省略无关项）：

```
-netdev socket,id=user.qemu-compose,fd=6
-device virtio-net,netdev=user.qemu-compose
```

### 5.2 coredump / journal

```bash
coredumpctl info 228662 --no-pager
```

```
Signal: 6 (ABRT)
Command Line: /usr/bin/qemu-system-x86_64 ... -name knowall ...
              -netdev socket,id=user.qemu-compose,fd=6 ...
Stack trace of thread 228662:
  #4 __assert_fail
  #5 qemu-system-x86_64 + 0x1a4338    # net_fill_rstate
  #6 qemu-system-x86_64 + 0x2cfb2a    # net_socket_send
  #7 qemu-system-x86_64 + 0x8d642d    # aio_dispatch
```

第一次崩溃（PID 8184）的堆栈偏移完全相同，命令行同样是 `-name knowall` +
`-netdev socket,id=user.qemu-compose,fd=6`。

### 5.3 passt 日志

`.../9e3a0f1ff807.../passt.log` 末尾：

```
71723.1423: Flow 1 (TCP connection): No tap activity for least 30s, send keepalive
...
71725.8849: Client connection closed, exiting
```

passt 是在 QEMU 死后才退出的，不是 passt 先挂导致 QEMU 退出。

### 5.4 排除 OOM / 手动关机 / guest 原因

```bash
free -h                          # 21G used, 41G available
journalctl -k --since ... | grep -i oom   # 无匹配
```

- 无 OOM killer 记录；
- guest 控制台在崩溃前约 20 小时无输出，没有 shutdown/reboot 交互；
- `qemu-compose ps -a` 中实例状态为 `exited`，退出原因是 QEMU SIGABRT；
- 宿主没有 suspend/resume 记录。

### 5.5 当前风险实例

```bash
qemu-compose ps -a
```

```
be17e9144bd2  ctf-challs  devbox:archlinux      1004  298073  running
d43ed86caa90  bb          devbox:archlinux-...  1002   29411  running
9e3a0f1ff807  knowall     devbox:archlinux      1003  228662  exited
```

这两个 running 实例的 QEMU 命令行也使用 passt，走同一条
`-netdev socket,fd=` → `net_socket_send()` 路径。

---

## 6. 根因分析

### 6.1 qemu-compose 的 passt 集成

`qemu_compose/instance/qemu_runner.py` 约 631–650 行：

```python
if self.config.network is None or self.config.network.lower() == 'user':
    passt_bin = shutil.which('passt')
    if passt_bin:
        self.using_passt = True
        self.passt_binary = passt_bin
        self._close_passt_socketpair()
        self.passt_socketpair = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.passt_fd = self.passt_socketpair[0].fileno()
        self.qemu_passt_fd = self.passt_socketpair[1].fileno()
        args.append('-netdev')
        args.append('socket,id=user.qemu-compose,fd=%d' % self.qemu_passt_fd)
        args.append('-device')
        args.append('virtio-net,netdev=user.qemu-compose')
    else:
        # 回退到 QEMU slirp：-netdev user,...
        ...
```

相关提交：

| commit | 内容 |
|---|---|
| `24e3075` | 有 passt 时默认使用 passt 做 user 网络 |
| `9a1eab5` | 第一版改用 QEMU stream netdev |
| `2dcc899` | 改为向 QEMU 传 connected fd（当前行为） |
| `78b27ec` | 让 passt 自己发现宿主 DNS |

也就是说：**只要宿主装了 passt（默认就会装），所有 user 网络 VM 都会走
`-netdev socket,fd=`，不再走 slirp。** 这正是崩溃路径。

### 6.2 QEMU 侧缺陷

QEMU v11.1.2 `net/socket.c`（`net_socket_send()`，约 155–190 行）：

```c
size = recv(s->fd, buf1, sizeof(buf1), 0);
if (size < 0) {
    if (errno != EWOULDBLOCK)
        goto eoc;
    /* BUG: EAGAIN/EWOULDBLOCK 时既不 return，也不清空 size */
} else if (size == 0) {
eoc:
    ...
    return;
}
buf = buf1;

ret = net_fill_rstate(&s->rs, buf, size);   /* size == -1 */
```

QEMU v11.1.2 `net/stream_data.c`（`net_stream_data_send()`，约 91–130 行）有相同问题：

```c
size = qio_channel_read(d->ioc, buf1, sizeof(buf1), NULL);
if (size < 0) {
    if (errno != EWOULDBLOCK)
        goto eoc;
    /* 同样没有 return */
} else if (size == 0) {
eoc:
    ...
    return G_SOURCE_REMOVE;
}
...
ret = net_fill_rstate(&d->rs, (const uint8_t *)buf, size);  /* size == -1 */
```

`net/net.c`（约 2100–2176 行）：

```c
int net_fill_rstate(SocketReadState *rs, const uint8_t *buf, int size)
{
    ...
    while (size > 0) {       /* size == -1，循环直接跳过 */
        ...
    }

    assert(size == 0);       /* 失败 -> SIGABRT */
    return 0;
}
```

补充：同一个文件里的 `net_socket_send_dgram()`（约 193 行）处理是正确的：
`if (size < 0) return;`，所以 dgram socket 不会触发这个断言。但 passt 的 `-F/--fd`
使用的是带 4 字节长度前缀的 stream 协议，不能简单把 socketpair 改成 `SOCK_DGRAM`。

**触发条件**：glib 的 fd watch 被唤醒（G_IO_IN），但 `recv()` 时数据已被消费或
读事件是虚假/重复的，非阻塞 socket 返回 `EAGAIN`。这是竞态，平时极少发生，但在
长时间运行、网络活动较多时概率累积。已知上游 issue：

- https://gitlab.com/qemu-project/qemu/-/issues/3285
  （标题即 `net_fill_rstate: Assertion 'size == 0' failed`，2026-01-29 报告，
  2026-08-21 仍为 open；报告者使用 colima，同样是 passt + QEMU socket netdev 组合）

### 6.3 为什么“换成 QEMU 自带 `-netdev passt`”不能解决问题

QEMU 10.1+ 确实内置了 `-netdev passt`，但它默认使用 stream 模式，底层就是
`net/stream_data.c`，与 `net/socket.c` 是同一个 bug（见 6.2 第二段）。
因此：

- `-netdev passt`（默认）→ **仍然会崩**；
- `-netdev passt,vhost-user=on` → 走 vhost-user，不经过 `net_fill_rstate`，
  才有可能规避；
- `-netdev user`（slirp）→ 不经过该路径，安全。

---

## 7. 可复现性

这是内核/glib 事件循环层面的竞态，**不建议为了写复现而长时间压测生产 VM**。
修复不依赖稳定复现，根因已经由源码和两次相同的 coredump 堆栈确认。

如需验证修复效果，建议：

1. 用修复后的 qemu-compose 启动一个测试 VM（不要用 knowall）。
2. 持续制造宿主侧网络事件，例如：
   - guest 内 `while true; do curl -s http://10.0.2.2:.../; sleep 1; done`；
   - 或用 `ports` 暴露 guest 服务，宿主循环访问；
   - 同时 `ping` / DNS 查询。
3. 运行 24–48 小时，检查：
   - `~/.local/share/qemu-compose/instance/<id>/qemu-compose.log` 不再出现
     `received signal 6` / `Assertion`；
   - `coredumpctl list` 不再新增 qemu core；
   - `qemu-compose ps -a` 中 VM 仍 running。

单元测试层面，修复 qemu-compose 的 passt 开关是确定性的，不需要等竞态。

---

## 8. 修复方案

### 方案 A（推荐先做）：增加 passt 开关，允许回退 slirp

**目标**：不改默认行为的前提下，让用户/单项目可以强制使用 QEMU slirp，彻底绕开
`net/socket.c`。

**实现建议（尽量小）**：

1. `QemuConfig` 增加字段（`qemu_compose/instance/qemu_runner.py` 约 156–205 行）：

   ```python
   passt: Optional[bool] = None   # None = auto; False = force slirp
   ```

   `from_dict()` 增加：

   ```python
   passt=d.get("passt"),
   ```

   `to_dict()` 当前返回 `self.__dict__`，会自动带上该字段。

2. `setup_qemu_args()`（约 631 行）改为：

   ```python
   passt_enabled = self.config.passt
   if passt_enabled is None:
       passt_enabled = os.environ.get(
           "QEMU_COMPOSE_NO_PASST", ""
       ).lower() not in ("1", "true", "yes", "on")

   passt_bin = shutil.which('passt') if passt_enabled else None
   ```

   其余 `if passt_bin:` 分支保持不变；`else:` 分支已经是 slirp。

3. 对应 YAML（`/home/ztx/prj/knowall/qemu-compose.yml`）：

   ```yaml
   passt: false
   ```

   或临时用环境变量：

   ```bash
   QEMU_COMPOSE_NO_PASST=1 qemu-compose up
   ```

4. 测试（`tests/test_passt_network.py`）新增：

   - `test_setup_skips_passt_when_env_disables_it`：
     `monkeypatch.setenv("QEMU_COMPOSE_NO_PASST", "1")`，
     断言 `runner.using_passt is False`，且 `runner._args` 中存在
     `user,id=user.qemu-compose`，不存在 `socket,id=user.qemu-compose,fd=`。
   - `test_config_passt_false_forces_slirp`：
     构造 `QemuConfig(..., passt=False)`，即使 `shutil.which` 返回
     `/usr/bin/passt`，也必须走 slirp。
   - 保留现有 `test_passt_port_arguments...`、`test_setup_uses_passt_fd_netdev...`、
     `test_setup_falls_back...`，确保默认行为不变。

5. README 增补一句：passt 可被 `passt: false` / `QEMU_COMPOSE_NO_PASST=1` 关闭。

**优点**：改动最小、可立即验证、不改变默认行为。
**缺点**：slirp 性能不如 passt；只是规避，不是根治 QEMU 的 bug。
**注意**：
- `command_start()` 合并配置时使用 `instance_config.to_dict() | config.to_dict()`，
  YAML 中未写的字段（值为 `None`）会覆盖实例里保存的值。因此对已有实例，优先
  使用 env 变量，或在每次 `up` 时明确写 `passt: false`。
- `qemu-compose start <id>` 不带 `-f` 时不会读取 YAML，最稳妥是 env 变量。
- 不建议改默认值为 slirp 后不告知用户；如果决定默认回退，需要在 README/CHANGELOG
  里明确写性能和端口转发行为变化。

### 方案 B（长期，保留 passt 性能）：改用 vhost-user 模式

**目标**：继续使用 passt，但走 QEMU 的 vhost-user netdev，不经过
`net_fill_rstate()`。

**已验证事实**（本机 QEMU 11.1.2 + passt 2026_10_02）：

- `-netdev passt,id=n0,vhost-user=on` + `-object memory-backend-memfd,...,share=on`
  + `-numa node,memdev=...` 可以正常启动；
- **不带共享内存 backend 时**，QEMU 会打印
  `Failed initializing vhost-user memory map, consider using -object memory-backend-file share=on`
  和 `falling back on userspace virtio`，随后在测试中直接 SIGSEGV。因此必须保证
  vhost-user 模式下 guest RAM 是 `share=on` 的。
- qemu-compose 目前只在有 virtiofs 卷时才添加
  `-object memory-backend-memfd,id=qc-mem,size=...,share=on`（`qemu_runner.py` 约 708–720 行）。
  knowall 有 4 个卷所以没问题；没有卷的 VM 必须额外补上，否则 vhost-user 会退化并崩溃。

**两种接法**：

1. 使用 QEMU 原生 `-netdev passt`（QEMU 自己 spawn/kill passt，推荐）：
   - 需要 QEMU >= 10.1（当前 11.1.2 满足）；
   - 参数至少包括：
     `-netdev passt,id=user.qemu-compose,vhost-user=on,address=10.0.2.15,netmask=255.255.255.0,gateway=10.0.2.2,path=/usr/bin/passt,...`
   - 端口转发映射到 `tcp-ports` / `udp-ports`（值格式同 passt 的 `-t` / `-u`，
     例如 `127.0.0.1/2222:22`、`8080:80`）。QAPI 定义见
     `qapi/net.json` 的 `NetdevPasstOptions` / `PasstPortForward`；QemuOpts 的数组
     写法需要实测。
   - passt 默认被 QEMU 加 `--quiet`；需要日志时设置 `quiet=off`，并通过
     `param` 追加 `-d`（`PasstParameter` 为字符串数组）。注意 QEMU 子进程 stderr
     的去向，不要重新引入 183MB 级别的无轮转日志。
   - QEMU 会负责杀掉 passt；需要验证 VM 退出后没有残留 passt 进程。
2. 保留 qemu-compose 自己 spawn passt，但改为：
   - `passt --vhost-user -s <unix_socket> ...`；
   - QEMU `-chardev socket,id=...,path=<unix_socket>` +
     `-netdev vhost-user,chardev=...,id=user.qemu-compose`；
   - 同样需要共享内存 backend。
   - 复杂度更高，但日志/生命周期控制仍在 qemu-compose 手里。

**验证矩阵**：

- 有卷 / 无卷的 VM 都能启动，guest 能 DHCP 拿到 `10.0.2.15`、网关 `10.0.2.2`；
- `ports` 的 TCP/UDP 转发不回归；
- guest DNS 正常（passt 自己发现宿主 DNS，不要硬编码 `--dns`）；
- `os.environ["GATEWAY_IP"] == "10.0.2.2"` 的兼容性不变；
- VM 停止后无残留 passt；
- 24–48h soak，无 assertion/core。

**回退**：QEMU < 10.1 或 vhost-user 初始化失败时，自动回退到方案 A 的 slirp，
不要回退到 stream passt。

### 方案 C（根治，但不在 qemu-compose 仓库内）：给 QEMU 打补丁

最小补丁（两处）：

```c
/* net/socket.c, net_socket_send() */
if (size < 0) {
    if (errno == EWOULDBLOCK) {
        return;
    }
    goto eoc;
} else if (size == 0) {
eoc:
    ...
}
```

```c
/* net/stream_data.c, net_stream_data_send() */
if (size < 0) {
    if (errno == EWOULDBLOCK) {
        return G_SOURCE_CONTINUE;
    }
    goto eoc;
} else if (size == 0) {
eoc:
    ...
}
```

说明：glib 的 fd watch 是 level-triggered，spurious wake 时直接返回是安全的；
如果仍有数据，下一次事件会再次触发。需要重新构建 `qemu-system-x86` 包
（Arch：改 PKGBUILD 后 `makepkg -si`），并在上游 issue #3285 反馈/提 MR。
这属于 QEMU 维护范围，不建议 qemu-compose 的修复 agent 顺手改系统 QEMU。

### 方案 D（缓解，不推荐当修复）：自动重启

用 systemd unit 或 wrapper 在 `qemu-compose up` 退出后自动重启。只能减少停机，
不能避免崩溃时的 guest 状态丢失，也不能避免 unclean shutdown，仅作为兜底。

---

## 9. 推荐决策

1. **立即**实施方案 A：默认行为不变，增加 `passt: false` / `QEMU_COMPOSE_NO_PASST=1`；
   先用它启动 knowall，保证不再崩。
2. **后续**实施方案 B：在测试 VM 上完成 vhost-user 改造和 24–48h soak，再切回 passt。
3. 有精力时给 QEMU 上游提方案 C 的补丁（issue #3285）。

---

## 10. 验收标准

修复 agent 完成后必须满足：

- [ ] `python3 -m pytest tests/test_passt_network.py -q` 全绿（当前 3 passed）。
- [ ] 未设置任何开关时，行为与 v1.1.3 一致：有 passt 仍使用 passt（回归测试）。
- [ ] `QEMU_COMPOSE_NO_PASST=1` 或 `passt: false` 时，QEMU 命令行包含
      `-netdev user,id=user.qemu-compose...`，不包含 `-netdev socket,...fd=`。
- [ ] 从 `/home/ztx/prj/knowall` 执行 `QEMU_COMPOSE_NO_PASST=1 qemu-compose up`
      能复用实例 `9e3a0f1ff807` 启动，磁盘数据仍在，guest 能联网。
- [ ] 端口转发（TCP/UDP）在 slirp 模式下不回归（用测试 VM 验证）。
- [ ] 重启 knowall 至少 2 次，`qemu-compose.log` 无 `Assertion` / `received signal 6`。
- [ ] 若实现方案 B：有卷/无卷 VM 都能启动，24–48h soak 无 core，
      `coredumpctl list` 无新增 qemu，停止后无残留 passt。
- [ ] README / CHANGELOG 记录新开关和性能取舍。
- [ ] 不提交无关的未跟踪文件（仓库当前有 `devbox.yml`、`examples/test/` 等 dirty 项）。

---

## 11. 实施步骤（建议顺序）

1. 在 `/home/ztx/prj/qemu-compose` 开分支，先读：
   - `qemu_compose/instance/qemu_runner.py`（`QemuConfig`、`setup_qemu_args`、
     `_passt_command`、`_start_passt`、`_stop_passt`）
   - `tests/test_passt_network.py`
   - `README.md`
2. 实施方案 A（env + config + tests + README）。
3. 跑测试：

   ```bash
   cd /home/ztx/prj/qemu-compose
   python3 -m pytest tests/test_passt_network.py -q
   ```

4. 构建并安装（需要 sudo，脚本会 `uv build` 后强制重装 wheel）：

   ```bash
   ./local_build_and_install.sh
   ```

5. 验证安装版本与仓库一致：

   ```bash
   diff -u /usr/lib/python3.14/site-packages/qemu_compose/instance/qemu_runner.py \
           /home/ztx/prj/qemu-compose/qemu_compose/instance/qemu_runner.py
   ```

6. 重启 knowall（**不要用 `down`/`rm`**）：

   ```bash
   cd /home/ztx/prj/knowall
   QEMU_COMPOSE_NO_PASST=1 qemu-compose up
   # 或先在 qemu-compose.yml 加 passt: false
   ```

7. 检查 QEMU 实际参数：

   ```bash
   pid=$(cat ~/.local/share/qemu-compose/instance/9e3a0f1ff807*/qemu.pid)
   tr '\0' ' ' < /proc/$pid/cmdline | tr ' ' '\n' | grep -A1 -- '-netdev'
   ```

   期望看到 `user,id=user.qemu-compose...`，而不是 `socket,id=...fd=`。

8. 如需方案 B，另开分支，先用一个**测试 VM**（不要用 knowall）完成 vhost-user
   改造和 soak，再迁移 knowall。

---

## 12. 注意事项 / 禁止操作

- **不要** `qemu-compose down knowall` / `rm knowall`：`down` 会停止并删除实例，
  `rm` 会删磁盘。当前磁盘在
  `~/.local/share/qemu-compose/instance/9e3a0f1ff8074e9dbc3357f86b6e4024/disk.qcow2`（约 6.8G）。
- **不要**删除 `qemu_config.json`、`storage.json`、`image-id`、`instance-id`。
- **不要**直接切到 QEMU 默认 `-netdev passt`：默认 stream 模式同 bug。
- **不要**在 `bb` / `ctf-challs` 上做实验；它们当前 running，可能承载任务。
- **不要**把 passt 的 `-d` 日志重新引入且不做轮转：当前
  `9e3a0f1f.../passt.log` 已达 183MB，`bb` 102MB，`ctf-challs` 41MB，
  宿主 `/home` 已 85% 使用、`/` 已 90% 使用。
- **不要**提交仓库里与本次修复无关的 dirty 文件。
- 当前系统没有免密 sudo；`local_build_and_install.sh` 需要用户在终端输入密码。
  如果 agent 无法交互式 sudo，改完代码后把构建/安装步骤留给用户执行。

---

## 13. 顺带清理建议（非阻塞）

- QEMU coredump 占用较大：
  - `core.qemu-system-x86...8184...zst`（3G，2026-10-27）
  - `core.qemu-system-x86...228662...zst`（2.4G，2026-10-28）
  - 本次诊断中做 vhost-user 负向测试还产生了一个 1.6M 的 PID 725957 core。
  - 可用 `sudo coredumpctl purge` 或按 PID 删除对应文件，释放 `/` 空间。
- 死实例的 passt 日志可直接删除（下次启动会 `wb` 截断）：
  `rm ~/.local/share/qemu-compose/instance/9e3a0f1ff807*/passt.log`
- 长期建议给 passt 日志加大小限制/轮转，或去掉 `-d`。

---

## 14. 附录

### 14.1 诊断用命令

```bash
# 实例列表
qemu-compose ps -a

# 崩溃日志
tail -100 ~/.local/share/qemu-compose/instance/9e3a0f1ff807*/qemu-compose.log

# 崩溃 core
coredumpctl info 228662 --no-pager
coredumpctl info 8184 --no-pager
coredumpctl list | grep qemu

# 内核/OOM 排除
journalctl -k --since "2026-10-28 10:50" --until "2026-10-28 11:10"
free -h

# 当前 passt / qemu
pgrep -a passt
ps -eo pid,etime,rss,comm,args | grep qemu-system

# 版本
qemu-system-x86_64 --version
pacman -Q qemu-system-x86 passt
qemu-compose --version

# 仓库/安装版本一致性
diff -u /usr/lib/python3.14/site-packages/qemu_compose/instance/qemu_runner.py \
        /home/ztx/prj/qemu-compose/qemu_compose/instance/qemu_runner.py
```

### 14.2 关键源码位置（QEMU v11.1.2）

| 文件 | 位置 | 内容 |
|---|---|---|
| `net/net.c` | 2100 | `net_fill_rstate()` |
| `net/net.c` | 2175 | `assert(size == 0)` |
| `net/socket.c` | 155 | `net_socket_send()` |
| `net/socket.c` | 163–166 | `recv()` / EAGAIN 分支 |
| `net/socket.c` | 186 | 把 `size` 传给 `net_fill_rstate()` |
| `net/stream_data.c` | 91 | `net_stream_data_send()` |
| `net/stream_data.c` | 99–102 | `qio_channel_read()` / EAGAIN 分支 |
| `net/stream_data.c` | 127 | 把 `size` 传给 `net_fill_rstate()` |

上游源码链接（tag `v11.1.2`）：

- https://gitlab.com/qemu-project/qemu/-/raw/v11.1.2/net/socket.c
- https://gitlab.com/qemu-project/qemu/-/raw/v11.1.2/net/stream_data.c
- https://gitlab.com/qemu-project/qemu/-/raw/v11.1.2/net/net.c

### 14.3 相关提交（qemu-compose）

```text
e918028 2026-10-25 Merge pull request #42 from zTrix/use_passt_user_network
78b27ec 2026-10-24 network: let passt discover host DNS servers
2dcc899 2026-10-24 network: pass passt a connected fd instead of unix socket
5701bf8 2026-10-24 network: avoid passt log-file permission issues
8acf3a0 2026-10-24 network: harden passt startup and logging
16c4711 2026-10-24 network: log passt to stderr to avoid syslog startup failure
9a1eab5 2026-10-24 network: use QEMU stream netdev for passt
24e3075 2026-10-24 network: use passt for user networking when available
```

### 14.4 knowall 配置（现状）

`/home/ztx/prj/knowall/qemu-compose.yml`：

```yaml
image: devbox:archlinux
name: knowall
qemu_args:
  - m: 8G
volumes:
  - /home/ztx/prj/knowall/workspace/skills/:/root/.pi/agent/skills/
  - ./config/:/root/.config/
  - ./workspace/:/data/workspace/
  - /home/ztx/prj/pensieve/:/data/pensieve/
before_script:
  - cp -a /home/ztx/.pi/agent/auth.json ./config/
boot_commands:
  - read_until: " login: "
  - write: "root\r"
  - read_until: "#"
  - wait: 0.2
  - write: "cd /root/.config/ && mkdir -p /root/.pi/agent/ && mv auth.json /root/.pi/agent/ && bash ./setup.sh\r"
  - interact: null
after_script:
  - reset -I
```

注意：`before_script` 使用相对路径 `./config/`，启动时必须在
`/home/ztx/prj/knowall` 目录下运行。

---

## 15. 参考

- QEMU upstream issue #3285:
  https://gitlab.com/qemu-project/qemu/-/issues/3285
- QEMU `-netdev passt` QAPI（`NetdevPasstOptions` / `PasstPortForward`）：
  https://gitlab.com/qemu-project/qemu/-/raw/v11.1.2/qapi/net.json
- QEMU vhost-user 网络文档：
  https://www.qemu.org/docs/master/system/devices/vhost-user.html
- passt 手册（`--vhost-user`、`-F/--fd`、`-t/--tcp-ports`、`-u/--udp-ports`）：
  `man passt`
