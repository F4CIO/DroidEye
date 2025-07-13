from datetime import datetime
import os
import sys

#

class CsLog:
    body = ''
    log_file_path = None

    def __init__(self, initial_body='', log_file_path=None):
        self.body = initial_body
        self.log_file_path = log_file_path

        #log_file_path = handler_for_file_system.build_sattelite_file_path(log_file_path)
        #self.log_file_path = log_file_path

        # Only add initial_body if it's not empty, and properly format it
        if initial_body:
            line = f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} {initial_body}'
            self.body = line + '\n'
            print(line)
            if self.log_file_path:
                with open(self.log_file_path, 'a') as log_file:
                    log_file.write(line + '\n')

    def get_body(self):
        return self.body

    def add_line(self, line: str):
        line = f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} {line}'

        self.body += line+'\n'

        print(line)

        if self.log_file_path:
            with open(self.log_file_path, 'a') as log_file:
                log_file.write(line+'\n')

    def get_new_lines(self, already_shown: int):
        """
        Return only the log lines that have been added *after* the given index.

        Parameters
        ----------
        already_shown : int
            The number of lines that the caller has already processed/displayed.

        Returns
        -------
        list[str]
            A list with all lines that were added after the index.
        """
        # Split the current body into individual lines
        lines = self.body.rstrip('\n').split('\n')

        # Guard against negative indexes and out-of-range values
        if already_shown < 0:
            already_shown = 0
        if already_shown >= len(lines):
            return []

        return lines[already_shown:]

# Example usage
if __name__ == "__main__":
    log = CsLog("Start log", "test.log")
    log.add_line("Another log line.") 