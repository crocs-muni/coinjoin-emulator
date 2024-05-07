from manager.wasabi_clients.wasabi_client_v1 import WasabiClientV1
from manager.wasabi_clients.wasabi_client_v2 import WasabiClientV2
from manager.wasabi_clients.wasabi_client_v204 import WasabiClientV204


def WasabiClient(version):
    if version < "2.0.0":
        return WasabiClientV1
    elif version >= "2.0.0" and version < "2.0.4":
        return WasabiClientV2
    else:
        return WasabiClientV204
