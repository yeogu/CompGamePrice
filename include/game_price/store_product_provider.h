#pragma once

#include "game_price/store_product.h"

#include <string>
#include <vector>

namespace game_price {

class StoreProductProvider {
public:
    virtual ~StoreProductProvider() = default;
    virtual Store store() const noexcept = 0;
    virtual std::vector<StoreProduct> findProducts(const std::string& gameId) const = 0;
};

}  // namespace game_price
