"""Default-deny firmware relay policy; this module never constructs firmware."""
import struct
from protocol import HELLO_DEVICE, HELLO_SERVER, DATA_DEVICE, DATA_SERVER, open_packet, validate_server_packet


def permitted(packet, direction, key):
    if len(packet)<4:return False
    magic=int.from_bytes(packet[:4],'little')
    if direction=='device':return magic in (HELLO_DEVICE, DATA_DEVICE)
    if magic==HELLO_SERVER:return True
    if magic!=DATA_SERVER or key is None:return False
    try:
        plain=validate_server_packet(open_packet(packet,key))
        length,subtype=struct.unpack_from('<HH',plain,28)
        if subtype==1:return True
        if subtype==3 and length>=70:
            # Mode/boost, configuration read and configuration write only.
            return int.from_bytes(plain[38:40],'little') in (2,4,5)
        # Subtype 2 advertises firmware; other envelopes are unsupported.
        return False
    except (ValueError,struct.error):return False
