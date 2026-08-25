"""B站 av 号与 BV 号互转（2023 年起的新算法）。"""

XOR_CODE = 23442827791579
MASK_CODE = 2251799813685247
MAX_AID = 1 << 51
ALPHABET = "FcwAPNKTMug3GV5Lj7EJnHpWsx4tb8haYeviqBz6rkCy12mUSDQX9RdoZf"
ENCODE_MAP = (8, 7, 0, 5, 1, 3, 2, 4, 6)
DECODE_MAP = tuple(reversed(ENCODE_MAP))
BASE = len(ALPHABET)


def av2bv(aid: int) -> str:
    chars = [""] * 9
    tmp = (MAX_AID | aid) ^ XOR_CODE
    for i in range(9):
        chars[ENCODE_MAP[i]] = ALPHABET[tmp % BASE]
        tmp //= BASE
    return "BV1" + "".join(chars)


def bv2av(bvid: str) -> int:
    chars = bvid[3:]
    tmp = 0
    for i in range(9):
        tmp = tmp * BASE + ALPHABET.index(chars[DECODE_MAP[i]])
    return (tmp & MASK_CODE) ^ XOR_CODE
