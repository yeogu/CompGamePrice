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

struct CommandLineOptions {
    AppCommand command{AppCommand::Demo};
    std::string gameName{"Stardew Valley"};
};

CommandLineOptions parseCommandLine(const std::vector<std::string>& arguments);
std::string commandLineHelp();

}  // namespace game_price
