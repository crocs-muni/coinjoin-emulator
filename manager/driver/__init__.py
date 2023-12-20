from abc import ABC, abstractmethod
from multiprocessing.pool import ThreadPool


class Driver(ABC):
    @abstractmethod
    def build(self, name, path):
        pass

    @abstractmethod
    def run(self, name, image, env=None, ports=None):
        pass

    @abstractmethod
    def stop(self, name):
        pass

    def stop_many(self, names):
        with ThreadPool() as p:
            p.map(lambda x: self.stop(x), names)

    @abstractmethod
    def download(self, name, src_path, dst_path):
        pass

    @abstractmethod
    def peek(self, name, path):
        pass

    @abstractmethod
    def upload(self, name, src_path, dst_path):
        pass

    @abstractmethod
    def cleanup(self):
        pass
