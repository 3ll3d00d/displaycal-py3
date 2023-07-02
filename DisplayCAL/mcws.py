import os.path
import time
import urllib
from typing import Optional, Tuple
from xml.etree import ElementTree as et
from xml.etree.ElementTree import Element
from DisplayCAL.log import get_file_logger

import requests
from requests import Session


class MediaServer:
    def __init__(
        self,
        ip: str,
        duration: int,
        chart_name: str,
        hdr: bool = False,
        auth: Optional[Tuple[str, str]] = None,
        secure: bool = False,
        parent=None,
        zone=0,
        sleep_multiplier: int = 1,
        display_pause_ms: int = 5000,
        patch_pause_ms: int = 300,
        patch_reads: int = 1,
    ):
        self.__parent = parent
        self.__sleep_multiplier = sleep_multiplier
        self.__duration = duration
        self.__ip = ip
        self.__auth = auth
        self.__secure = secure
        self.__chart_name = chart_name
        self.__episode = "hdr" if hdr else "sdr"
        self.__zone = zone
        self.__display_pause_ms = display_pause_ms
        self.__patch_pause_ms = patch_pause_ms
        self.__base_url = f"http{'s' if secure else ''}://{ip}/MCWS/v1"
        self.__session: Optional[Session] = None
        self.__token = None
        self.__starting = True
        self.__patch_reads = patch_reads
        self.__logger = get_file_logger("untethered")
        self.__logger.info(
            f"[mcws {self.__chart_name}] Will connect to {ip} in {self.__episode} mode"
        )

    @property
    def patch_reads(self):
        return self.__patch_reads

    def as_dict(self) -> dict:
        return {self.__ip: (self.__auth, self.__secure)}

    def __repr__(self):
        suffix = f" [{self.__auth[0]}]" if self.__auth else " [Unauthenticated]"
        return f"{self.__ip}{suffix}"

    def __init_session(self) -> bool:
        self.__token = None
        url = f"{self.__base_url}/Authenticate"
        self.__session = requests.Session()
        self.__session.auth = self.__auth
        r = self.__session.get(url, timeout=(1, 5))
        if r.status_code == 200:
            response = et.fromstring(r.content)
            if response:
                r_status = response.attrib.get("Status", None)
                if r_status == "OK":
                    for item in response:
                        if item.attrib["Name"] == "Token":
                            self.__token = item.text
        if self.connected:
            return True
        else:
            raise ValueError(f"Authentication failure {r}")

    @property
    def connected(self) -> bool:
        return self.__session is not None

    def __ensure_session(self):
        if not self.connected:
            self.__init_session()

    def ensure_playing(self, allow_retries=6, is_retry: bool = True):
        zone_id, file_key, play_state, file_name = self.__get_playback_info()
        if play_state == "Wrong Zone":
            self.__activate_zone()
            time.sleep(0.25 * self.__sleep_multiplier)
            self.ensure_playing(allow_retries=allow_retries - 1)
        elif file_name:
            if file_name == self.__chart_name:
                if play_state == "Stopped":
                    self.__logger.info(f"[mcws {self.__chart_name}] is stopped")
                    self.__play()
                    self.ensure_playing(allow_retries=allow_retries - 1)
                elif play_state == "Playing":
                    self.__logger.info(f"[mcws {self.__chart_name}] is playing")
                    self.__pause()
                    self.ensure_playing(allow_retries=allow_retries - 1)
                elif play_state == "Paused":
                    if self.__starting:
                        self.__display_video()
                        self.__osd(False)
                        self.__starting = False
                elif play_state == "Opening..." or play_state == "Waiting":
                    self.__logger.info(
                        f"[mcws {self.__chart_name}] waiting for playback to start, backing off"
                    )
                    self.__starting = True
                    time.sleep(1 * self.__sleep_multiplier)
                    self.ensure_playing(allow_retries=allow_retries - 1)
                else:
                    self.__logger.info(
                        f"[mcws {self.__chart_name}] unknown state, backing off"
                    )
                    time.sleep(0.5 * self.__sleep_multiplier)
                    self.ensure_playing(allow_retries=allow_retries - 1)
            elif file_name == "Media Center" and is_retry:
                self.__logger.info(
                    f"[mcws {self.__chart_name}] Backing off from intermediate state"
                )
                time.sleep(0.5 * self.__sleep_multiplier)
                self.ensure_playing(allow_retries=allow_retries - 1)
            else:
                if allow_retries:
                    self.__logger.info(f"[mcws {self.__chart_name}] Ensure stopped")
                    self.__stop()
                    time.sleep(0.1 * self.__sleep_multiplier)
                    self.__logger.info(
                        f"[mcws {self.__chart_name}] Initiating playback"
                    )
                    self.__start()
                    time.sleep(0.5 * self.__sleep_multiplier)
                    self.__logger.info(f"[mcws {self.__chart_name}] Checking playback")
                    self.ensure_playing(allow_retries=allow_retries - 1)
                else:
                    raise ValueError(
                        f"No more retries, {self.__chart_name} is not playing"
                    )
        else:
            if allow_retries:
                self.__logger.info(
                    f"[mcws {self.__chart_name}] Nothing playing, initiating playback"
                )
                self.__start()
                time.sleep(0.5 * self.__sleep_multiplier)
                self.ensure_playing(allow_retries=allow_retries - 1)
            else:
                raise ValueError(f"Unable to start playback of {self.__chart_name}")

    def __activate_zone(self):
        return self.__get_xml_and_return(
            f"{self.__base_url}/Playback/SetZone", add_zone=True
        )

    def display_patch(self, patch_index: int, allow_retry: int = 3):
        self.ensure_playing(is_retry=False)
        target_position = (patch_index * self.__duration) + 1
        self.__logger.info(
            f"[mcws {self.__chart_name}] Showing patch {patch_index} at position {target_position}"
        )
        if self.__set_position(target_position):
            pause_secs = (self.__patch_pause_ms * self.__sleep_multiplier) / 1000.0
            self.__logger.info(
                f"[mcws {self.__chart_name}] Waiting {pause_secs:.3g}s for patch {patch_index} to display"
            )
            time.sleep(pause_secs)
            actual_position = self.__get_position()
            if actual_position < 1:
                if allow_retry:
                    self.ensure_playing()
                    self.display_patch(patch_index, allow_retry=allow_retry - 1)
                else:
                    raise ValueError(f"Unable to play patch {patch_index}")
            elif actual_position == target_position:
                self.__logger.info(
                    f"[mcws {self.__chart_name}] Position updated to {target_position} for patch {patch_index}"
                )
            else:
                if allow_retry:
                    self.__logger.info(
                        f"[mcws {self.__chart_name}] Position should be {target_position} but is {actual_position}, retrying in 100ms"
                    )
                    time.sleep(0.1 * self.__sleep_multiplier)
                    self.display_patch(patch_index, allow_retry=allow_retry - 1)
                else:
                    raise ValueError(f"Unable to play patch {patch_index}")

    def __set_position(self, position: int) -> bool:
        return self.__get_xml_and_return(
            f"{self.__base_url}/Playback/Position",
            params={"Position": position},
            add_zone=True,
        )

    def __get_position(self) -> int:
        def parse(response):
            pos = -1
            if response:
                for child in response:
                    if (
                        child.tag == "Item"
                        and child.attrib.get("Name", "") == "Position"
                    ):
                        pos = int(child.text)
            self.__logger.info(f"[mcws {self.__chart_name}] position: {pos}")
            return pos

        val = self.__get_xml_and_return(
            f"{self.__base_url}/Playback/Position", parser=parse, add_zone=True
        )
        return -1 if not val else val

    def __get_playback_info(self) -> Tuple[int, int, str, str]:
        def parse(response):
            file_key = None
            state = None
            status = None
            file_name = None
            zone_id = None
            for child in response:
                if child.tag == "Item":
                    n = child.attrib.get("Name", "")
                    if n == "FileKey":
                        file_key = int(child.text)
                    elif n == "Status":
                        status = child.text
                    elif n == "State":
                        state = int(child.text)
                    elif n == "Name":
                        file_name = child.text
                    elif n == "ZoneID":
                        zone_id = int(child.text)
            if zone_id == self.__zone:
                if state == 2 and status != "Opening..." and status != "Waiting":
                    play_state = "Playing"
                elif state == 1:
                    play_state = "Paused"
                elif state == 0:
                    play_state = "Stopped"
                elif status:
                    play_state = status
                else:
                    play_state = "Unknown"
            else:
                play_state = "Wrong Zone"
            formatted = f"zone: {zone_id}, file_key: {file_key}, state: {state} / {status} / {play_state}, filename: {file_name}"
            self.__logger.info(f"[mcws {self.__chart_name}] Found {formatted}")
            return zone_id, file_key, play_state, file_name

        return self.__get_xml_and_return(
            f"{self.__base_url}/Playback/Info",
            params={"Fields": "Name"},
            parser=parse,
        )

    def __pause(self):
        return self.__get_xml_and_return(
            f"{self.__base_url}/Playback/Pause", params={"State": "1"}, add_zone=True
        )

    def __play(self):
        return self.__get_xml_and_return(
            f"{self.__base_url}/Playback/Play", add_zone=True
        )

    def __osd(self, on: bool):
        return self.__get_xml_and_return(
            f"{self.__base_url}/UserInterface/OSD", params={"On": "1" if on else "0"}
        )

    def __start(self):
        file_key = self.__find_file_key()
        return self.__get_xml_and_return(
            f"{self.__base_url}/Playback/PlayByKey",
            params={"Key": file_key},
            add_zone=True,
        )

    def __stop(self):
        return self.__get_xml_and_return(f"{self.__base_url}/Playback/ClearPlaylist")

    def __find_file_key(self) -> str:
        self.__ensure_session()
        url = f"{self.__base_url}/Files/Search"
        params = urllib.parse.urlencode(
            {
                "Action": "json",
                "Fields": "Key",
                "Query": f"[Name]=[{self.__chart_name}] [Media Type]=Video [Media Sub Type]=Test Clip [Episode]={self.__episode}",
            },
            quote_via=urllib.parse.quote,
        )
        r = self.__session.get(url, auth=self.__auth, timeout=(1, 5), params=params)
        if r.status_code == 200:
            results = r.json()
            if results:
                if len(results) == 1:
                    return results[0]["Key"]
        raise ValueError(f"No match found for {self.__chart_name}")

    def __display_video(self, allow_set=True):
        def parse(response):
            mode = 0
            i_mode = 0
            for child in response:
                if child.attrib.get("Name", "") == "Mode":
                    mode = int(child.text)
                elif child.attrib.get("Name", "") == "InternalMode":
                    i_mode = child.text
            self.__logger.info(
                f"[mcws {self.__chart_name}] mode: {mode}, InternalMode: {i_mode}"
            )
            return mode

        mode = self.__get_xml_and_return(
            f"{self.__base_url}/UserInterface/Info", parser=parse
        )
        if mode != 2:
            if allow_set:
                time.sleep(0.25 * self.__sleep_multiplier)
                self.__get_xml_and_return(
                    f"{self.__base_url}/Control/MCC",
                    params={"Command": 22000, "Parameter": 2, "Block": 1},
                )
                time.sleep((self.__display_pause_ms * self.__sleep_multiplier) / 1000.0)
                return self.__display_video(allow_set=False)
            else:
                return False
        else:
            return True

    def __get_xml_and_return(self, url, params=None, parser=None, add_zone=False):
        params = params if params else {}
        if add_zone and self.__zone != -1:
            params["Zone"] = self.__zone
        params = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        p = f" params: {params}" if params else ""
        self.__logger.info(f"[mcws {self.__chart_name}] {url}{p}")
        self.__ensure_session()
        r = self.__session.get(url, auth=self.__auth, timeout=(1, 5), params=params)
        if r.status_code == 200:
            response: Element = et.fromstring(r.content)
            if response is not None:
                # print(et.dump(response))
                r_status = response.attrib.get("Status", None)
                if r_status == "OK":
                    self.__logger.info(f"[mcws {self.__chart_name}] OK")
                    if parser:
                        return parser(response)
                    else:
                        return True
                else:
                    self.__logger.info(f"[mcws {self.__chart_name}] {r_status}")
        self.__logger.info(f"[mcws {self.__chart_name}] FAIL")
        return False

    @staticmethod
    def __now():
        from datetime import datetime

        return datetime.utcnow().isoformat(sep=" ", timespec="milliseconds")
