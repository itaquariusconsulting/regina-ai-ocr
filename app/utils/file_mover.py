import os
import shutil

"""Utility class to safely move files between directories."""
class FileMover:
    @staticmethod
    def move(file_path: str, target_folder: str):
        """
        Moves a file to the target folder.
        - Creates folder if missing.
        - Overwrites if file exists.
        """
        try:
            if not os.path.exists(target_folder):
                os.makedirs(target_folder)

            filename = os.path.basename(file_path)
            destination = os.path.join(target_folder, filename)

            # Remove existing file in destination to avoid permission errors on move
            if os.path.exists(destination):
                os.remove(destination)

            shutil.move(file_path, destination)
            print(f"   [MOVED] -> {target_folder}/{filename}")

        except OSError as e:
            print(f"   [SYSTEM ERROR] Could not move file: {e}")