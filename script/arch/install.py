#!/usr/bin/env python3

import os
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

def get_fs_uuid(target):
    uuid_map_dir_path = '/dev/disk/by-uuid/'
    for name in os.listdir(uuid_map_dir_path):
        content = os.readlink(uuid_map_dir_path + name)
        if os.path.normpath(os.path.join(uuid_map_dir_path, content)) == target:
            return name
    return None

def prepare_disk():
    disk = find_first_disk()
    logger.info('found first block device %s, do partition...' % disk)

    args = ["/usr/bin/env", "parted", "-s", disk, "unit", "s", "mklabel", "gpt", "mkpart", "ESP", "fat32", "2048s", "526335s", "set", "1", "esp", "on", "mkpart", "primary", "ext4", "526336s", "100%", "print"]
    subprocess.run(args, check=True)

    args = ["/usr/bin/env", "mkfs.fat", "-F32", disk + '1']
    subprocess.run(args, check=True)

    args = ["/usr/bin/env", "mkfs.ext4", "-F", "-q", disk + '2']
    subprocess.run(args, check=True)

    args = ["/usr/bin/env", "mount", disk + '2', "/mnt"]
    subprocess.run(args, check=True)

    args = ["/usr/bin/env", "mkdir", "-p", "/mnt/boot"]
    subprocess.run(args, check=True)

    args = ["/usr/bin/env", "mount", disk + '1', "/mnt/boot"]
    subprocess.run(args, check=True)

    return disk

def main():
    logging.basicConfig(level=logging.INFO)

    disk = prepare_disk()

    args = ["/usr/bin/env", "pacstrap", "-K", "/mnt", "base", ]
    subprocess.run(args, check=True)

    args = "/usr/bin/env genfstab -U /mnt >> /mnt/etc/fstab"
    subprocess.run(args, check=True, shell=True)

    fs_uuid = get_fs_uuid(disk + '2')
    if not fs_uuid:
        raise Exception('uuid not found for %s' % (disk + '2'))

    args = ["/usr/bin/env", "mkdir", "-p", "/mnt/boot/loader/entries/"]
    subprocess.run(args, check=True)
    
    with open('/mnt/boot/loader/entries/arch.conf', 'w') as f:
        f.write('''
title    Arch Linux
linux    /vmlinuz-linux
initrd   /initramfs-linux.img
options  root=UUID=%s rw
''' % fs_uuid)

    with open('/mnt/etc/hostname', 'w') as f:
        f.write('arch\n')

    args = "/usr/bin/env arch-chroot /mnt /bin/bash -c 'pacman -Sy -q --noconfirm linux linux-firmware dhcpcd openssh openresolv netctl && mkinitcpio -p linux && bootctl --path=/boot install && echo _ | passwd root --stdin'"
    subprocess.run(args, check=True, shell=True)

if __name__ == '__main__':
    main()
