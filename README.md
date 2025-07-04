
# qemu-compose

qemu-compose aims to provide a docker-compose style composer for qemu command, with advanced scripting feature as well as http support for cloud init or general purpose provisioning.

bring up a qemu VM by providing a qemu-compose.yml and run `qemu-compose up`

## Advantages

 - Simple and robust
 - No libvirt stuff, no complex
 - support `before_script` and `after_script` for setup and cleanup
 - support `boot_commands` for vm provisioning (implemented using jsonlisp for expressive power which apparently is turing-complete)
 - support `http_serve` for cloudinit
 - env interpolation for advanced configuration

## Examples and Screenshot

bring up ubuntu cloudimg qemu vm and run a interactive shell


```
$ cd ./script/ubuntu-cloudimg__amd64/
$ qemu-compose up
```

![svg](https://github.com/username/repository/blob/main/assets/ubuntu-cloudimg.svg)
