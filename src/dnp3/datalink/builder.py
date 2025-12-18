"""Frame builder utilities for constructing data link frames.

Provides convenient factory methods for building common frame types
with correct control byte settings per IEEE 1815-2012.
"""

from dnp3.core.enums import LinkFunctionCode
from dnp3.datalink.control import ControlByte
from dnp3.datalink.frame import DataLinkFrame


def build_primary_frame(
    destination: int,
    source: int,
    function_code: LinkFunctionCode,
    dir_from_master: bool,
    fcb: bool = False,
    fcv: bool = False,
    user_data: bytes = b"",
) -> DataLinkFrame:
    """Build a primary station frame.

    Args:
        destination: Destination address (0-65535).
        source: Source address (0-65535).
        function_code: Primary function code.
        dir_from_master: True if frame is from master station.
        fcb: Frame count bit (for confirmed data).
        fcv: Frame count valid bit.
        user_data: Optional user data payload.

    Returns:
        DataLinkFrame ready for transmission.
    """
    control = ControlByte(
        dir_from_master=dir_from_master,
        prm=True,  # Primary message
        fcb=fcb,
        fcv=fcv,
        function_code=function_code.value,
    )
    return DataLinkFrame.build(
        destination=destination,
        source=source,
        control=control,
        user_data=user_data,
    )


def build_secondary_frame(
    destination: int,
    source: int,
    function_code: LinkFunctionCode,
    dir_from_master: bool,
    dfc: bool = False,
) -> DataLinkFrame:
    """Build a secondary station frame (response).

    Args:
        destination: Destination address.
        source: Source address.
        function_code: Secondary function code.
        dir_from_master: True if frame is from master station.
        dfc: Data flow control bit (uses FCB position).

    Returns:
        DataLinkFrame ready for transmission.
    """
    control = ControlByte(
        dir_from_master=dir_from_master,
        prm=False,  # Secondary message
        fcb=dfc,  # DFC uses FCB position in secondary frames
        fcv=False,  # Reserved in secondary frames
        function_code=function_code.value,
    )
    return DataLinkFrame.build(
        destination=destination,
        source=source,
        control=control,
        user_data=b"",  # Secondary frames have no user data
    )


def build_unconfirmed_user_data(
    destination: int,
    source: int,
    dir_from_master: bool,
    user_data: bytes,
) -> DataLinkFrame:
    """Build an unconfirmed user data frame.

    This is the most common frame type for DNP3 communication.
    No acknowledgment is expected from the receiver.

    Args:
        destination: Destination address.
        source: Source address.
        dir_from_master: True if from master station.
        user_data: User data payload (transport layer data).

    Returns:
        DataLinkFrame with function code 4 (unconfirmed user data).
    """
    return build_primary_frame(
        destination=destination,
        source=source,
        function_code=LinkFunctionCode.PRI_UNCONFIRMED_USER_DATA,
        dir_from_master=dir_from_master,
        fcb=False,
        fcv=False,
        user_data=user_data,
    )


def build_confirmed_user_data(
    destination: int,
    source: int,
    dir_from_master: bool,
    fcb: bool,
    user_data: bytes,
) -> DataLinkFrame:
    """Build a confirmed user data frame.

    Expects an ACK/NACK response from the receiver.

    Args:
        destination: Destination address.
        source: Source address.
        dir_from_master: True if from master station.
        fcb: Frame count bit (alternates between messages).
        user_data: User data payload.

    Returns:
        DataLinkFrame with function code 3 (confirmed user data).
    """
    return build_primary_frame(
        destination=destination,
        source=source,
        function_code=LinkFunctionCode.PRI_CONFIRMED_USER_DATA,
        dir_from_master=dir_from_master,
        fcb=fcb,
        fcv=True,  # FCV always set for confirmed data
        user_data=user_data,
    )


def build_reset_link_state(
    destination: int,
    source: int,
    dir_from_master: bool,
) -> DataLinkFrame:
    """Build a reset link state frame.

    Used to reset the remote link state machine.

    Args:
        destination: Destination address.
        source: Source address.
        dir_from_master: True if from master station.

    Returns:
        DataLinkFrame with function code 0 (reset link state).
    """
    return build_primary_frame(
        destination=destination,
        source=source,
        function_code=LinkFunctionCode.PRI_RESET_LINK_STATE,
        dir_from_master=dir_from_master,
        fcb=False,
        fcv=False,
    )


def build_request_link_status(
    destination: int,
    source: int,
    dir_from_master: bool,
) -> DataLinkFrame:
    """Build a request link status frame.

    Requests link layer status from remote station.

    Args:
        destination: Destination address.
        source: Source address.
        dir_from_master: True if from master station.

    Returns:
        DataLinkFrame with function code 9 (request link status).
    """
    return build_primary_frame(
        destination=destination,
        source=source,
        function_code=LinkFunctionCode.PRI_REQUEST_LINK_STATUS,
        dir_from_master=dir_from_master,
        fcb=False,
        fcv=False,
    )


def build_test_link_state(
    destination: int,
    source: int,
    dir_from_master: bool,
    fcb: bool,
) -> DataLinkFrame:
    """Build a test link state frame.

    Tests link layer without sending user data.

    Args:
        destination: Destination address.
        source: Source address.
        dir_from_master: True if from master station.
        fcb: Frame count bit.

    Returns:
        DataLinkFrame with function code 2 (test link state).
    """
    return build_primary_frame(
        destination=destination,
        source=source,
        function_code=LinkFunctionCode.PRI_TEST_LINK_STATE,
        dir_from_master=dir_from_master,
        fcb=fcb,
        fcv=True,
    )


def build_ack(
    destination: int,
    source: int,
    dir_from_master: bool,
    dfc: bool = False,
) -> DataLinkFrame:
    """Build an ACK response frame.

    Acknowledges receipt of a confirmed message.

    Args:
        destination: Destination address.
        source: Source address.
        dir_from_master: True if from master station.
        dfc: Data flow control bit.

    Returns:
        DataLinkFrame with function code 0 (ACK).
    """
    return build_secondary_frame(
        destination=destination,
        source=source,
        function_code=LinkFunctionCode.SEC_ACK,
        dir_from_master=dir_from_master,
        dfc=dfc,
    )


def build_nack(
    destination: int,
    source: int,
    dir_from_master: bool,
    dfc: bool = False,
) -> DataLinkFrame:
    """Build a NACK response frame.

    Negative acknowledgment for a confirmed message.

    Args:
        destination: Destination address.
        source: Source address.
        dir_from_master: True if from master station.
        dfc: Data flow control bit.

    Returns:
        DataLinkFrame with function code 1 (NACK).
    """
    return build_secondary_frame(
        destination=destination,
        source=source,
        function_code=LinkFunctionCode.SEC_NACK,
        dir_from_master=dir_from_master,
        dfc=dfc,
    )


def build_link_status(
    destination: int,
    source: int,
    dir_from_master: bool,
    dfc: bool = False,
) -> DataLinkFrame:
    """Build a link status response frame.

    Response to a request link status message.

    Args:
        destination: Destination address.
        source: Source address.
        dir_from_master: True if from master station.
        dfc: Data flow control bit.

    Returns:
        DataLinkFrame with function code 11 (link status).
    """
    return build_secondary_frame(
        destination=destination,
        source=source,
        function_code=LinkFunctionCode.SEC_LINK_STATUS,
        dir_from_master=dir_from_master,
        dfc=dfc,
    )


def build_not_supported(
    destination: int,
    source: int,
    dir_from_master: bool,
) -> DataLinkFrame:
    """Build a not supported response frame.

    Indicates the requested function is not supported.

    Args:
        destination: Destination address.
        source: Source address.
        dir_from_master: True if from master station.

    Returns:
        DataLinkFrame with function code 15 (not supported).
    """
    return build_secondary_frame(
        destination=destination,
        source=source,
        function_code=LinkFunctionCode.SEC_NOT_SUPPORTED,
        dir_from_master=dir_from_master,
        dfc=False,
    )
