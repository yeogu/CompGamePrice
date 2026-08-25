#pragma once

#include "game_price/domain/domain_types.h"

#include <cstdint>

namespace game_price {

struct Money {
    std::int64_t minorAmount{};
    Currency currency{Currency::KRW};
};

inline bool operator==(const Money& left, const Money& right) noexcept {
    return left.minorAmount == right.minorAmount && left.currency == right.currency;
}

inline bool operator!=(const Money& left, const Money& right) noexcept {
    return !(left == right);
}

}  // namespace game_price
