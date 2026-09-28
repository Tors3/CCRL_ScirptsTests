# third_party

## stockfish-10-win

Official Stockfish 10 Windows release (GPL-3.0, see `stockfish-10-win/Copying.txt`),
used as the CCRL reference for machine calibration (`bench`, reference i7-4770K = 2054 ms).

| file | sha256 |
|---|---|
| Windows/stockfish_10_x64.exe | febfa362b329d23ec1193321f94eb8db899c6b771d7cfe34b900dd84f054519d |
| Windows/stockfish_10_x64_bmi2.exe | 25108b8c3db1f9e54b06722ba0049fc7ba3cd425b401f21db818e00214aba0f4 |
| Windows/stockfish_10_x64_popcnt.exe | fb96c809736da06abf12e347b28e09ca886b715b3f7ff18dc650ff32ca43efb7 |

Only 64-bit builds are kept (the 32-bit binary caused a wrong bench on 2026-09-22).
Source code is in `stockfish-10-win/src`.
