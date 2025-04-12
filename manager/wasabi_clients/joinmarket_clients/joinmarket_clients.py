from .joinmarket_client_base import JoinMarketClientServer

class MakerClient(JoinMarketClientServer):
    """
    This class implements the logic for a maker.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.maker_running = False

    def update_status(self):
        """
        Get the status of the client and update the maker_running flag.
        """
        response = super().update_status()
        self.maker_running = response.get("maker_running", False)
        return response

    def update(self, current_block, current_round) -> int:
        """
        Start the maker if it is not running.
        """
        self.update_status()

        if self.is_paused(current_block):
            return 0

        if not self.maker_running:
            offer = self.get_offer(current_round)
            self.start_maker(**offer)
            print(f"Starting maker {self.name}")
            self.maker_running = True
        return 0

class TakerClient(JoinMarketClientServer):
    """
    This class implements the logic for a taker that does *not* have tumbler options.
    """

    def update_status(self):
        """
        Get the status of the client and update the coinjoin_in_process flag.
        """
        response = super().update_status()
        self.coinjoin_in_process = response.get("coinjoin_in_process", False)
        return response

    def update(self, current_block, current_round):
        """
        Start a coinjoin if none is running and the client is not paused.
        Stop the coinjoin if it has been running for 8 blocks.
        """
        self.update_status()

        delta = 0
        if not self.coinjoin_in_process and not self.is_paused(current_block):
            offer = self.get_offer(current_round)
            offer["destination"] = self.get_new_address()
            self.start_coinjoin(**offer)
            self.coinjoin_start = current_block
            self.coinjoin_in_process = True
            delta = +1
            print(f"Starting coinjoin {self.name}")
            print(f"- coinjoin rounds: {current_round + delta} (block {current_block})".ljust(60))

        # TODO: The 8 block limit could be a parameter.
        elif self.coinjoin_in_process and self.coinjoin_start + 8 < current_block:
            self.stop_coinjoin()
            self.coinjoin_in_process = False
            self.next_coinjoin_allowed = current_block + self.time_between_rounds
            delta = -1
            print(f"Stopping coinjoin {self.name}")
            print(f"- coinjoin rounds: {current_round + delta} (block {current_block})".ljust(60))
        return delta

class TumblerTakerClient(JoinMarketClientServer):
    """
    This subclass is for a taker with tumbler options.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tumbler_options = kwargs.get("tumbler_options", None)
        self.last_schedule = None
        self.coinjoin_completed = True

    def update_status(self):
        """
        Get the status of the client and updates flags
        The conjoin_completed flag is determined by comparing the current and
        last schedule, which gets updated after each coinjoin.
        """
        response = super().update_status()
        self.coinjoin_in_process = response.get("coinjoin_in_process", False)
        schedule = response.get("schedule", None)
        if schedule != self.last_schedule:
            self.coinjoin_completed = True
            self.last_schedule = schedule
        return response

    def update(self, current_block, current_round):
        """
        Start a coinjoin if none is running and the client is not paused.
        Increment the round count if a coinjoin has completed.
        """
        self.update_status()

        if not self.coinjoin_in_process and not self.is_paused(current_block):
            print(f"Starting scheduled coinjoin for {self.name}")
            response = self.run_schedule()
            self.last_schedule = response["schedule"]
            print(response)
            self.coinjoin_in_process = True
            self.coinjoin_start = current_block
            return 0

        delta = 0
        if self.coinjoin_completed:
            delta = +1
            self.coinjoin_completed = False
            print("Coinjoin for {self.name} completed.")
            print(self.get_schedule())
            print(f"- coinjoin rounds: {current_round + delta} (block {current_block})".ljust(60))

        return delta