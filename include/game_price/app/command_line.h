#pragma once

#include <string>
#include <vector>

namespace game_price {

enum class AppCommand {
    Demo,
    Collect,
    Compare,
    History,
    Help
};

enum class AppExitCode {
    Success = 0,
    RuntimeError = 1,
    UsageError = 2,
    GameNotFound = 3,
    NoData = 4,
    CollectionFailed = 5
};

struct CommandLineOptions {
    AppCommand command{AppCommand::Demo};
    std::string gameName{"Stardew Valley"};
};

CommandLineOptions parseCommandLine(const std::vector<std::string>& arguments);
std::string commandLineHelp();

}  // namespace game_price
