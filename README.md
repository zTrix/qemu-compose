
# resident

opposite of vagrant, qemu manager

usage:

```
$ resident.py ~/vm/arch/archlinux-2025.05.01-x86_64.iso
```

## uv and pip

```
$ uv pip install --editable ./qemu-package/
```


## using linux 

 - use bios use kernel param and initrd param, https://github.com/TrinityEmulator/TrinityEmulator/blob/a570269885e296d22e58b14a4a8b100775679b9b/tests/acceptance/linux_initrd.py#L71
 - https://github.com/TrinityEmulator/TrinityEmulator/blob/a570269885e296d22e58b14a4a8b100775679b9b/tests/vm/basevm.py#L192
 - https://cloud-images.ubuntu.com/releases/plucky/release-20250424/
 - https://wiki.archlinux.org/title/Arch_Linux_on_a_VPS
 - https://github.com/TrinityEmulator/TrinityEmulator/blob/a570269885e296d22e58b14a4a8b100775679b9b/tests/vm/ubuntu.i386
 - 参考 vagrant 里面的 qemu provider
 - https://github.com/hashicorp/vagrant/blob/73db3ce45e946145f6b76d5d73156586381ecb14/plugins/communicators/ssh/communicator.rb#L726
 - 

```
ztx       164251  1.3  0.0 1253636 31760 pts/16  Sl+  10:57   0:06 /home/ztx/.config/packer/plugins/github.com/hashicorp/qemu/packer-plugin-qemu_v1.1.2_x5.0_linux_amd64 start builder --protobuf -packer-default-plugin-name-
ztx       164302  100  0.3 1555284 210512 pts/16 Sl+  10:57   8:35 /usr/bin/qemu-system-x86_64 -nographic -display none -m 512M -name ubuntu-kvm -netdev user,id=user.0,hostfwd=tcp::3188-:22 -device virtio-net,netdev=user.0 -drive file=output-qemu/ubuntu-kvm,if=virtio,cache=writeback,discard=ignore,format=qcow2 -drive file=/home/ztx/prj/resident/packer/iso/ubuntu-24.04.2-live-server-amd64.iso,media=cdrom -vnc 127.0.0.1:73 -boot once=d -machine type=pc,accel=kvm -smp 1
```

# TODO

 - [ ] 使用 qemu 的 kernel 和 initrd 参数来运行跑起来，并把文件系统准备好，而且能够 build 出来最新的
 - [ ] 处理 qemu package，变成一个可以 import 的目录
 - [ ] 接入一个 tty，然后 tmux 可以 a 上去？
