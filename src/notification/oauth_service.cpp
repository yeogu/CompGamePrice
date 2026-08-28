#include "game_price/notification/oauth_service.h"

#include <stdexcept>

namespace game_price {
OAuthService::OAuthService(AccountRepository& repository):repository_(repository){}
AuthResult OAuthService::completeLogin(const OAuthProfile& profile) const {
    if(profile.providerUserId.empty()) throw std::invalid_argument("OAuth subject is required");
    auto user=repository_.findUserByExternalIdentity(profile.provider,profile.providerUserId);
    if(!user){
        // Never merge accounts merely because providers return the same email.
        const auto synthetic=toString(profile.provider)+"-"+profile.providerUserId+"@social.local";
        user=repository_.createUser(synthetic,"!social");
        repository_.addExternalIdentity(user->id,profile);
    }
    return AuthResult{*user,repository_.createSession(user->id)};
}
ExternalIdentity OAuthService::linkIdentity(std::int64_t userId,const OAuthProfile& profile) const {
    const auto owner=repository_.findUserByExternalIdentity(profile.provider,profile.providerUserId);
    if(owner && owner->id!=userId) throw std::invalid_argument("social account belongs to another user");
    if(owner) throw std::invalid_argument("social account is already linked");
    return repository_.addExternalIdentity(userId,profile);
}
}  // namespace game_price
