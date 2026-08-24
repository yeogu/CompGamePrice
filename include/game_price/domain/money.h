#pragma once

#include "game_price/domain/domain_types.h"

#include <cstdint>

namespace game_price {

struct Money {
    std::int64_t minorAmount{};
    Currency currency{Currency::KRW};
};

}  // namespace game_price
