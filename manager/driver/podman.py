from io import BytesIO
import os
import tarfile
from . import Driver
import podman
import docker


class PodmanDriver(Driver):
    def __init__(self):
        self.client = podman.PodmanClient()

    def build(self, name, path):
        import docker

        docker.from_env().images.build(path=path, tag=name, rm=True)

    def run(self, name, image, env=None, ports=None):
        self.client.containers.run(
            image,
            detach=True,
            auto_remove=True,
            name=name,
            hostname=name,
            ports=ports or {},
            environment=env or {},
        )

    def stop(self, name):
        try:
            self.client.containers.get(name).stop()
            print(f"- stopped {name}")
        except docker.errors.NotFound:
            pass

    def download(self, name, src_path, dst_path):
        try:
            stream, _ = docker.from_env().containers.get(name).get_archive(src_path)

            fo = BytesIO()
            for d in stream:
                fo.write(d)
            fo.seek(0)
            with tarfile.open(fileobj=fo) as tar:
                tar.extractall(dst_path)

            print(f"- stored backend logs")
        except:
            print(f"- could not store backend logs")

    def peek(self, name, path):
        stream, _ = docker.from_env().containers.get(name).get_archive(path)

        fo = BytesIO()
        for d in stream:
            fo.write(d)
        fo.seek(0)
        with tarfile.open(fileobj=fo) as tar:
            return tar.extractfile(os.path.basename(path)).read().decode()

    def upload(self, name, src_path, dst_path):
        fo = BytesIO()
        with tarfile.open(fileobj=fo, mode="w") as tar:
            tar.add(src_path, os.path.basename(dst_path))
        fo.seek(0)
        docker.from_env().containers.get(name).put_archive(
            os.path.dirname(dst_path), fo
        )

    def cleanup(self):
        containers = list(
            filter(
                lambda x: x.attrs["Config"]["Image"]
                in ("btc-node", "wasabi-backend", "wasabi-client"),
                docker.from_env().containers.list(),
            )
        )
        self.stop_many(map(lambda x: x.name, containers))
