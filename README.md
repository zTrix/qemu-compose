
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

bring up ubuntu cloudimg qemu vm and run a interactive shell


```
$ cd ./script/ubuntu-cloudimg__amd64/
$ qemu-compose up
```

Demo:

[![asciicast](https://raw.githubusercontent.com/zTrix/qemu-compose/refs/heads/main/assets/726386.svg)](https://asciinema.org/a/726386)

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
