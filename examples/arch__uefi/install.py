#!/usr/bin/env python3
import os
import sys
import time
import json
import shlex
import logging
import subprocess

logger = logging.getLogger('arch_installer')

def ensure_exist(filepath):
    if os.path.exists(filepath):
        return filepath
    return None

def find_first_disk():
    blocks = os.listdir('/sys/block/')

    if not blocks:
        return None

    for d in ['a', 'b', 'c', 'd', 'e', 'f', 'g']:
        for i in ['s', 'v']:
            name = i + 'd' + d

            if name in blocks:
                return ensure_exist('/dev/' + name)

    for item in blocks:
        if item.startswith('loop') or item.startswith('sr'):
            continue
        return ensure_exist('/dev/' + item)

    return None

def find_first_netlink():
    links = os.listdir('/sys/class/net/')
    if not links:
        return None

    for l in links:
        if l.startswith('e'):
            return l
    return None

def get_fs_uuid(target):
    uuid_map_dir_path = '/dev/disk/by-uuid/'
    for name in os.listdir(uuid_map_dir_path):
        content = os.readlink(uuid_map_dir_path + name)
        if os.path.normpath(os.path.join(uuid_map_dir_path, content)) == target:
            return name
    return None

def run_cmd(cmd, shell=False):
    if isinstance(cmd, list):
        print('$ ' + shlex.join(cmd))
    else:
        print('$ ' + cmd)
    subprocess.run(cmd, check=True, shell=shell)

def get_cmd_output_json(cmd):
    try:
        output = subprocess.check_output(cmd, shell=False, text=True)
        return json.loads(output)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}")
        return None

def prepare_disk(disk):

    if disk is None:
        disk = find_first_disk()

    if not disk:
        raise Exception('could not find a disk for installation, aborting')

    logger.info('found first block device %s, do partition...' % disk)

    args = ["/usr/bin/env", "parted", "-s", disk, "unit", "s", "mklabel", "gpt", "mkpart", "ESP", "fat32", "2048s", "526335s", "set", "1", "esp", "on", "mkpart", "primary", "ext4", "526336s", "100%", "print"]
    run_cmd(args)

    obj = get_cmd_output_json(["/usr/bin/env", "lsblk", "-n", disk, "-J"])
    disk_parts = obj["blockdevices"][0]["children"]
    disk_parts.sort(key=lambda x:x['name'])

    disk_part1 = '/dev/' + disk_parts[0]["name"]
    disk_part2 = '/dev/' + disk_parts[1]["name"]
    logger.info("found disk parts: %s, %s" % (disk_part1, disk_part2))

    args = ["/usr/bin/env", "mkfs.fat", "-F32", disk_part1]
    run_cmd(args)

    args = ["/usr/bin/env", "mkfs.ext4", "-F", "-q", disk_part2]
    run_cmd(args)

    args = ["/usr/bin/env", "mount", disk_part2, "/mnt"]
    run_cmd(args)

    args = ["/usr/bin/env", "mkdir", "-p", "/mnt/boot"]
    run_cmd(args)

    args = ["/usr/bin/env", "mount", disk_part1, "/mnt/boot"]
    run_cmd(args)

    return disk, disk_parts

def main(disk=None):
    logging.basicConfig(level=logging.INFO)

    disk, disk_parts = prepare_disk(disk)
    disk_part2 = '/dev/' + disk_parts[1]["name"]

    while True:
        output = subprocess.check_output(['/usr/bin/systemctl', 'show', 'pacman-init.service'], shell=False, text=True)
        if 'SubState=exited' in output:
            break
        print('waiting for pacman-init, sleep 1...')
        time.sleep(1)

    with open('/etc/pacman.d/mirrorlist', 'w') as f:
        f.write('Server = https://mirrors.tuna.tsinghua.edu.cn/archlinux/$repo/os/$arch\n')

    args = ["/usr/bin/env", "pacstrap", "-K", "/mnt", "base", ]
    run_cmd(args)

    args = "/usr/bin/env genfstab -U /mnt >> /mnt/etc/fstab"
    run_cmd(args, shell=True)

    fs_uuid = get_fs_uuid(disk_part2)
    if not fs_uuid:
        raise Exception('uuid not found for %s' % (disk_part2))

    args = ["/usr/bin/env", "mkdir", "-p", "/mnt/boot/loader/entries/"]
    run_cmd(args)
    
    with open('/mnt/boot/loader/entries/arch.conf', 'w') as f:
        f.write('''title    Arch Linux
linux    /vmlinuz-linux
initrd   /initramfs-linux.img
options  root=UUID=%s console=tty0 console=ttyS0 rw
''' % fs_uuid)

    with open('/mnt/etc/hostname', 'w') as f:
        f.write('arch\n')

    args = "/usr/bin/env arch-chroot /mnt /bin/bash -c 'pacman -Sy -q --noconfirm linux linux-firmware dhcpcd openssh openresolv netctl && mkinitcpio -p linux && bootctl --path=/boot install && /bin/bash -c \"echo root:_ | chpasswd -c SHA512\"'"
    run_cmd(args, shell=True)

    args = ["/usr/bin/env", "sed", "-i", r'/#PermitRootLogin/c\PermitRootLogin yes', "/mnt/etc/ssh/sshd_config"]
    run_cmd(args)

    link_name = find_first_netlink()
    if link_name:
        with open('/mnt/etc/netctl/%s-dhcp' % link_name, 'w') as f:
            f.write('''Interface=%s
Connection=ethernet
IP=dhcp
''' % link_name)

    escaped_unit_name = subprocess.check_output(['/usr/bin/systemd-escape', '--template=netctl@.service', link_name + '-dhcp'], shell=False, text=True)
    if escaped_unit_name:
        escaped_unit_name = escaped_unit_name.strip()

    os.makedirs('/mnt/etc/systemd/system/multi-user.target.wants/', exist_ok=True)
    os.makedirs('/mnt/etc/systemd/system/%s.d/' % escaped_unit_name, exist_ok=True)

    with open("/mnt/etc/systemd/system/%s.d/profile.conf" % escaped_unit_name, 'w') as f:
        f.write('''[Unit]
BindsTo=sys-subsystem-net-devices-%s.device
After=sys-subsystem-net-devices-%s.device
''' % (link_name, link_name))

    args = "/usr/bin/env arch-chroot /mnt /bin/bash -c 'systemctl enable sshd && ln -vs /usr/lib/systemd/system/netctl@.service \"/etc/systemd/system/multi-user.target.wants/%s\"'" % escaped_unit_name
    run_cmd(args, shell=True)

    run_cmd('sync', shell=True)

    run_cmd('echo __deadbeef__', shell=True)

if __name__ == '__main__':
    disk = sys.argv[1] if len(sys.argv) > 1 else None
    main(disk=disk)
