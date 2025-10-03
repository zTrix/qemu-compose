import os
import fcntl
import struct
import errno
import logging

logger = logging.getLogger(__name__)

VHOST_VSOCK_SET_GUEST_CID = 0x4008AF60

VSOCK_PATH = '/dev/vhost-vsock'


def get_available_guest_cid(start_guest_cid: int = 1000) -> None | int:
    """
    get available guest cid

    :param guest_cid: start_guest_cid
    :return: available guest cid if success, else None
    """
    try:
        vsock_fd = os.open(VSOCK_PATH, os.O_RDWR)
    except FileNotFoundError:
        logger.info(f"could not open {VSOCK_PATH}, make sure vhost_vsock module loaded by running `modprobe vhost_vsock` using root")
        return None
    except PermissionError:
        logger.info(f"could not open {VSOCK_PATH}, please run as root")
        return None

    guest_cid = start_guest_cid
    try:
        while guest_cid <= 0xFFFFFFFF:  # U32_MAX
            cid_c = struct.pack('L', guest_cid)
            try:
                fcntl.ioctl(vsock_fd, VHOST_VSOCK_SET_GUEST_CID, cid_c)
            except IOError as e:
                if e.errno == errno.EADDRINUSE:
                    guest_cid += 1
                    continue
                else:
                    raise e
            else:
                return guest_cid
        return None
    finally:
        os.close(vsock_fd)
