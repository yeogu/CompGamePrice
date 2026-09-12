#pragma once

#include "game_price/collection/store_product_provider.h"

#include <cstdint>
#include <string>
#include <vector>

namespace game_price {

class EpicGamesProvider final : public StoreProductProvider {
public:
    explicit EpicGamesProvider(
        const std::string& dataPath,
        Store store = Store::EpicGamesStore);
    Store store() const noexcept override;
    std::vector<StoreProduct> findProducts(const std::string& gameId) const override;
    std::vector<ProviderRejection> findRejections(
        const std::string& gameId) const override;

private:
    struct RawProduct {
        std::string offerId;
        std::string gameId;
        std::int64_t regularPriceMinor{};
        std::int64_t currentPriceMinor{};
        Currency currency{Currency::KRW};
        int discountPercent{};
        std::string compatibleOs;
        bool active{false};
    };

    std::vector<RawProduct> products_;
    std::vector<ProviderRejection> rejections_;
    Store store_;
};

}  // namespace game_price
