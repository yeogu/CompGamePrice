# Cross-Platform Game Price Prototype

A minimal C++17 prototype that normalizes three different local store data
formats and compares their prices through a common provider interface.

## Build and run

```sh
cmake -S . -B build
cmake --build build
./build/game_price_tracker
```

No external libraries are required.
