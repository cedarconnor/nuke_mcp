"""Create a new, portable 4x4 native workflow fixture directory without overwriting files."""
import argparse
from pathlib import Path
import struct
import zlib


def prepare(directory):
    folder=Path(directory).resolve()
    folder.mkdir(parents=True,exist_ok=False)
    def chunk(name,data):
        return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    raw=b''.join(b'\0'+bytes([26,51,77,255])*4 for _ in range(4))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',4,4,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
    (folder/'plate.png').write_bytes(png)
    (folder/'workflow_fixture.nk').write_text(
        'Root {\n first_frame 1\n last_frame 2\n format "4 4 0 0 4 4 1 MCP_4"\n}\n'
        'Read {\n inputs 0\n file "'+(folder/'plate.png').as_posix()+'"\n first 1\n last 2\n name MCP_Base\n}\n'
        'Write {\n file "'+(folder/'review.exr').as_posix()+'"\n file_type exr\n name MCP_Review\n}\n'
        'Constant {\n inputs 0\n color {0.05 0.1 0.15 0}\n format "4 4 0 0 4 4 1 MCP_4"\n name MCP_Light\n}\n',encoding='utf-8')
    return folder


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args()
    print(prepare(args.directory))
