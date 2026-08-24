# CompGamePrice

AI를 활용하여 개발하는 크로스 플랫폼 게임 가격 비교 Prototype입니다.

서로 다른 Steam, Google Play, Apple App Store 로컬 데이터 형식을 공통
`StoreProduct` 모델로 정규화하고, 공통 Provider 인터페이스를 통해
Stardew Valley의 최저가를 비교합니다.

## Build and run

```sh
cmake -S . -B build
cmake --build build
./build/game_price_tracker
```

외부 라이브러리는 사용하지 않으며 C++17이 필요합니다.
