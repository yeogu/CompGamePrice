#pragma once

#include "game_price/collection/store_product_provider.h"

#include <cstdint>
#include <string>
#include <vector>

namespace game_price {

class AppleAppStoreProvider final : public StoreProductProvider {
public:
    explicit AppleAppStoreProvider(const std::string& dataPath);
    Store store() const noexcept override;
    std::vector<StoreProduct> findProducts(const std::string& gameId) const override;

private:
    struct RawProduct {
        std::string trackId;
        std::string gameId;
        std::int64_t amountWon{};
        std::string deviceFamilies;
        bool availableForSale{false};
    };

    std::vector<RawProduct> products_;
};

}  // namespace game_price
