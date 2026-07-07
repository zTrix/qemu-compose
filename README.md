
# qemu-compose

qemu-compose aims to provide a docker-compose style composer for qemu command, with advanced scripting feature as well as http support for cloud init or general purpose provisioning.

Bring up a qemu VM by providing a qemu-compose.yml and run `qemu-compose up`

## Advantages

 - Very simple and robust, written of several pure python scripts, depends on `qemu` commands only.
 - No libvirt stuff, no daemon process, no xml config, no complex abstraction, just a simple wrapper around qemu args.
 - support `before_script` and `after_script` for setup and cleanup
 - support `boot_commands` for vm provisioning (implemented using tty communication, gui not supported yet, and use jsonlisp for expressive power which apparently is turing-complete)
 - support `http_serve` for cloudinit
 - env interpolation for advanced configuration

## Installation

```
$ pip install qemu-compose
```

## Examples and Screenshot

Example 1: pull archlinux docker image and run archlinux image directly with systemd init just like normal vm boot:

```
$ qemu-compose pull --boot systemd --kernel /boot/vmlinuz-linux --initrd /boot/initramfs-linux.img --disk-size 256G dockerproxy.net/library/archlinux:latest
$ qemu-compose run dockerproxy.net/library/archlinux:latest
```

Demo:

[![asciicast](https://raw.githubusercontent.com/zTrix/qemu-compose/refs/heads/main/assets/1260286.svg)](https://asciinema.org/a/1260286)


Example 2: download and bring up qemu vm with ubuntu cloudimg disk file, run a interactive shell


```
$ cd ./script/ubuntu-cloudimg__amd64/
$ qemu-compose up
```

Demo:

[![asciicast](https://raw.githubusercontent.com/zTrix/qemu-compose/refs/heads/main/assets/726386.svg)](https://asciinema.org/a/726386)

## Pull OCI/Docker Images

`qemu-compose pull` imports an OCI/Docker image into the local qemu-compose image store as a bootable qcow2 image.

The imported image is stored under:

```
~/.local/share/qemu-compose/image/<sha256>/
```

and can then be listed, tagged, removed, or run with the normal image commands:

```
$ qemu-compose images
$ qemu-compose run IMAGE[:TAG]
$ qemu-compose tag SOURCE_IMAGE TARGET_IMAGE
$ qemu-compose rmi IMAGE
```

### Dependencies

The pull/import path uses external tools:

- `skopeo`: pull/copy OCI images from registries
- `umoci`: unpack OCI images
- `qemu-img`: create qcow2 disks
- `guestfish`: format and populate the qcow2 root filesystem
- `openssl`: hash `--root-password` values

On Arch Linux:

```
$ sudo pacman -S --needed skopeo umoci qemu-img libguestfs openssl
```

Registry proxies are configured through the normal environment variables used by `skopeo`, for example:

```
$ HTTPS_PROXY=http://127.0.0.1:8123 qemu-compose pull ...
```

### Basic Container Boot

Docker/OCI images are root filesystems, not full VM disks. They do not normally include a bootloader, kernel, or initramfs, so `pull` requires direct-boot assets:

- `--kernel`: Linux kernel file copied into the qemu-compose image
- `--initrd`: initramfs file copied into the qemu-compose image

Example:

```
$ qemu-compose pull \
    --kernel /boot/vmlinuz-linux \
    --initrd /boot/initramfs-linux.img \
    --disk-size 512M \
    alpine:3.20
```

By default, `--boot container` is used. qemu-compose injects `/qemu-compose-init` into the rootfs and boots with:

```
init=/qemu-compose-init
```

That init script mounts basic pseudo-filesystems and runs the OCI image's `Entrypoint`/`Cmd`. This is useful for lightweight container-like VM images.

### Systemd Boot

Use `--boot systemd` for images that contain systemd, such as Arch Linux:

```
$ qemu-compose pull \
    --boot systemd \
    --kernel /boot/vmlinuz-linux \
    --initrd /boot/initramfs-linux.img \
    --disk-size 2G \
    registry-mirrors.dev.in.chaitin.net/library/archlinux:latest
```

In systemd mode, qemu-compose prepares the rootfs for a normal serial-console VM boot:

- boots `init=/usr/lib/systemd/systemd`
- writes `/etc/fstab` for `/dev/vda1`
- clears `/etc/machine-id` so systemd regenerates it
- enables `serial-getty@ttyS0.service` when available
- writes a DHCP `systemd-networkd` profile and enables `systemd-networkd` when available
- enables `systemd-resolved`, `sshd`, and `qemu-guest-agent` when those units exist
- masks `systemd-imds-generator` when present to avoid noisy minimal-image boot warnings

This mode makes an OCI Arch Linux rootfs boot to a normal systemd multi-user login prompt, but it does not install missing packages. If the image does not contain systemd or SSH packages, `pull` will not add them.

### Root Login

By default, `pull` unlocks root with an empty password so serial console login works immediately:

```
archlinux login: root
Password:
```

Press Enter at the password prompt.

To set a real root password instead:

```
$ qemu-compose pull \
    --boot systemd \
    --root-password testpass \
    --kernel /boot/vmlinuz-linux \
    --initrd /boot/initramfs-linux.img \
    registry-mirrors.dev.in.chaitin.net/library/archlinux:latest
```

`--empty-root-password` is also accepted explicitly, but it cannot be used together with `--root-password`.

### Updating Existing Imports

The image directory name is based on the OCI image digest. If the digest is already present, use `--force` to rebuild it with different options:

```
$ qemu-compose pull --force --boot systemd ...
```

Use `--keep-workdir` to keep temporary import files when debugging a failed import.

### Limitations

- `pull` currently creates one ext4 root partition at `/dev/vda1`.
- It uses direct kernel boot, not GRUB/UEFI boot inside the imported disk.
- Container boot mode runs the OCI command; systemd boot mode boots systemd, but does not install extra packages.
- Full devbox images with custom packages, dotfiles, certificates, GRUB, or cloud-init still require a provisioning/build layer on top of the imported rootfs.

## SSH Helper

qemu-compose provides a helper to invoke ssh with the instance key and safe defaults.

- Usage: `qemu-compose ssh [OPTIONS] VMID COMMAND [ARG...]`
- Defaults added by qemu-compose:
  - `-o StrictHostKeyChecking=no`
  - `-o UserKnownHostsFile=/dev/null`
  - `-i ~/.local/share/qemu-compose/instance/VMID/ssh-key`
  - appends `root@vsock%<cid>` as the default destination (falls back to `root@vsock%${cid}` if CID is unknown)

Examples:

```
# Print the default ssh command that would be used for a given VMID
$ qemu-compose ssh <vmid>
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i ~/.local/share/qemu-compose/instance/<vmid>/ssh-key root@vsock%<cid>

# Connect using vsock destination (cid recorded when the VM booted)
$ qemu-compose ssh <vmid> root@vsock%<cid>

# Connect over TCP instead (override destination and add your own options)
$ qemu-compose ssh <vmid> -p 2222 root@127.0.0.1

# Run a remote command
$ qemu-compose ssh <vmid> root@vsock%<cid> uname -a
```

Notes:
- The instance key is generated at first boot and stored under `~/.local/share/qemu-compose/instance/<vmid>/ssh-key`.
- Any ssh options you pass will be forwarded; the last-specified option wins.

## Down Command

Stop and remove a VM instance.

```
$ qemu-compose down [identifier] [options]
```

Options:
- `identifier`: Instance ID, unique prefix, or assigned name (optional if config file exists)
- `-f, --file FILE`: Compose configuration file to parse for instance name
- `--force`: Force removal without confirmation

Examples:

```
# Stop and remove instance by name
$ qemu-compose down my-vm

# Use config file to auto-detect instance name
$ cd ./script/ubuntu-cloudimg__amd64/
$ qemu-compose down

# Use specified config file
$ qemu-compose down -f /path/to/qemu-compose.yml

# Force removal
$ qemu-compose down --force my-vm
```

Note: If no identifier is provided, qemu-compose will look for `qemu-compose.yml` or `qemu-compose.yaml` in the current directory and use the `name` field as the instance identifier.

## Tag Command

Create a tag that refers to an image, similar to `docker tag`.

```
$ qemu-compose tag SOURCE_IMAGE[:TAG] TARGET_IMAGE[:TAG]
```

- `SOURCE_IMAGE[:TAG]`: Source image identifier (can be image ID, name, or name:tag)
- `TARGET_IMAGE[:TAG]`: Target image name and optional tag (defaults to `latest` if not specified)

Behavior:
- If the target tag already exists on another image, it will be moved to the source image
- Tags are stored in the image's `manifest.json` file under the `repo_tags` field

Examples:

```
# Tag an image by ID
$ qemu-compose tag 94a0434d0f73 devbox:archlinux

# Tag an image by name
$ qemu-compose tag my-image:v1 my-image:latest

# Create a new tag for an existing image
$ qemu-compose tag ubuntu:20.04 ubuntu:focal

# Replace an existing tag (moves tag from one image to another)
$ qemu-compose tag new-image:v1 existing-tag:latest
```

Notes:
- Image IDs can be specified as full SHA256 digest or unique prefix
- When a tag already exists on a different image, the tag is moved (not copied) to the new image
- Use `qemu-compose images` to list all images and their tags
