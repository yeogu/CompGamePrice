#pragma once

#include "game_price/store_product.h"

#include <string>
#include <vector>

namespace game_price {

class StoreProductProvider {
public:
    virtual ~StoreProductProvider() = default;
    virtual std::vector<StoreProduct> findProducts(const std::string& gameId) const = 0;
};

}  // namespace game_price
