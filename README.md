
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

# TODO

 - [ ] 使用 qemu 的 kernel 和 initrd 参数来运行跑起来，并把文件系统准备好，而且能够 build 出来最新的
