#pragma once

#include "game_price/domain/store_product.h"

#include <cstdint>

namespace game_price {

inline constexpr std::int64_t MaximumSupportedPriceMinor = 100'000'000;

void validateStoreProduct(const StoreProduct& product);

}  // namespace game_price
