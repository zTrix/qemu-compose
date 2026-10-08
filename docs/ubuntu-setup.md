
# ubuntu tools are tooooooooooooooooooooooooooo old, here is the fix for common issues

```
sudo apt-get install -y virtiofsd python3-pycryptodome uidmap qemu-utils socat
sudo pip3 install --force-reinstall --break-system-packages --no-deps --upgrade qemu-compose

# for virtiofsd
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0

# kvm access
sudo usermod -aG kvm ubuntu
newgrp kvm
```

for invalid key when qemu-compose ssh, run the following using new version of ssh-keygen

```
ssh-keygen -p -f /home/ubuntu/.local/share/qemu-compose/instance/827a486979aa4c338926eb5b7677bd2e/ssh-key
```
