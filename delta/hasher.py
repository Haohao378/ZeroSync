import struct
import blake3
import zstandard as zstd
from typing import Generator, Tuple

class HashUtils:
    _ZSTD_COMPRESSOR = zstd.ZstdCompressor(level=3, threads=-1)

    @staticmethod
    def blake3_hash(data: memoryview) -> bytes:
        return blake3.blake3(data).digest()

    @staticmethod
    def compress(data: memoryview) -> bytes:
        return HashUtils._ZSTD_COMPRESSOR.compress(data)

class FastCDC:
    GEAR = [6671450048746545909, 2260594373694414473, 1964704676911719473, 5903076607460267789, 6627967034971081317, 4474119649562137337, 3476210192614641777, 3697088214518997843, 1864395139408124297, 2057814146035223481, 2627019256010384749, 575296281981053309, 5024788820366544781, 2504762045719164189, 4472996002850174245, 6034949845970764185]

    def __init__(self, min_size: int=16384, avg_size: int=65536, max_size: int=262144):
        self.min_size = min_size
        self.avg_size = avg_size
        self.max_size = max_size
        if len(self.GEAR) < 256:
            import random
            random.seed(42)
            self.GEAR = [random.getrandbits(64) | 1 for _ in range(256)]
        mask_bits = self._log2(avg_size)
        self.mask_s = (1 << mask_bits + 1) - 1
        self.mask_l = (1 << mask_bits - 1) - 1

    def _log2(self, value: int) -> int:
        return value.bit_length() - 1

    def generate_chunks(self, data_view: memoryview) -> Generator[Tuple[int, int], None, None]:
        data_len = len(data_view)
        offset = 0
        while offset < data_len:
            chunk_min = min(offset + self.min_size, data_len)
            chunk_max = min(offset + self.max_size, data_len)
            chunk_avg = min(offset + self.avg_size, data_len)
            if chunk_min == data_len:
                yield (offset, data_len - offset)
                break
            fp = 0
            chunk_end = chunk_min
            while chunk_end < chunk_avg:
                fp = (fp << 1) + self.GEAR[data_view[chunk_end]] & 18446744073709551615
                if not fp & self.mask_s:
                    break
                chunk_end += 1
            if chunk_end == chunk_avg:
                while chunk_end < chunk_max:
                    fp = (fp << 1) + self.GEAR[data_view[chunk_end]] & 18446744073709551615
                    if not fp & self.mask_l:
                        break
                    chunk_end += 1
            yield (offset, chunk_end - offset)
            offset = chunk_end