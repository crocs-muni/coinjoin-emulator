from .wasabi_client_base import WasabiClientBase


class WasabiClientV204(WasabiClientBase):

    def __init__(
        self,
        host="localhost",
        port=37128,
        name="wasabi-client",
        proxy="",
        version="2.0.4",
        skip_rounds=[],
    ):
        super().__init__(host, port, name, proxy, version, skip_rounds)
