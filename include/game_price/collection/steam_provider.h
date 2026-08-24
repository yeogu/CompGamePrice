#pragma once

#include "game_price/collection/store_product_provider.h"

#include <cstdint>
#include <string>
#include <vector>

namespace game_price {

class SteamProvider final : public StoreProductProvider {
public:
    explicit SteamProvider(const std::string& dataPath);
    Store store() const noexcept override;
    std::vector<StoreProduct> findProducts(const std::string& gameId) const override;

private:
    struct RawProduct {
        std::string appId;
        std::string gameId;
        std::int64_t finalPriceWon{};
        std::string platformFlags;
        bool available{false};
    };

    std::vector<RawProduct> products_;
};

}  // namespace game_price
