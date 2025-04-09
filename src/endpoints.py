import time
from http import HTTPStatus
from typing import Annotated, Optional, Dict, Any, cast
import os
import base64

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, Response
from sbase import BaseCase

from src.consts import CHALLENGE_TITLES
from src.models import (
    LinkRequest,
    LinkResponse,
    Solution,
    ImageDownloadRequest,
)

from .utils import get_sb, logger, save_screenshot

router = APIRouter()

SeleniumDep = Annotated[BaseCase, Depends(get_sb)]


@router.get("/", include_in_schema=False)
def read_root():
    """Redirect to /docs."""
    logger.debug("Redirecting to /docs")
    return RedirectResponse(url="/docs", status_code=301)


@router.get("/health")
def health_check(sb: SeleniumDep):
    """Health check endpoint."""
    health_check_request = read_item(
        LinkRequest.model_construct(url="https://google.com"),
        sb,
    )

    if health_check_request.solution.status != HTTPStatus.OK:
        raise HTTPException(
            status_code=500,
            detail="Health check failed",
        )

    return {"status": "ok"}


@router.post("/v1")
def read_item(request: LinkRequest, sb: SeleniumDep) -> LinkResponse:
    """Handle POST requests."""
    start_time = int(time.time() * 1000)
    sb.uc_open_with_reconnect(request.url)
    logger.debug(f"Got webpage: {request.url}")
    source_bs = sb.get_beautiful_soup()
    title_tag = source_bs.title
    if title_tag and title_tag.string in CHALLENGE_TITLES:
        logger.debug("Challenge detected")
        sb.uc_gui_click_captcha()
        logger.info("Clicked captcha")

    if sb.get_title() in CHALLENGE_TITLES:
        save_screenshot(sb)
        raise HTTPException(status_code=500, detail="Could not bypass challenge")

    cookies = sb.get_cookies()
    for cookie in cookies:
        name = cookie["name"]
        value = cookie["value"]
        cookie["size"] = len(f"{name}={value}".encode())

        cookie["session"] = False
        if "expiry" in cookie:
            cookie["expires"] = cookie["expiry"]

    return LinkResponse(
        message="Success",
        solution=Solution(
            userAgent=sb.get_user_agent(),
            url=sb.get_current_url(),
            status=200,
            cookies=cookies,
            headers={},
            response=str(sb.get_beautiful_soup()),
        ),
        start_timestamp=start_time,
    )


@router.post("/v1/download-image")
def download_image(request: ImageDownloadRequest, sb: SeleniumDep) -> Response:
    """
    Download an image by navigating to the page and capturing network requests.
    Returns the image as a response with the appropriate content type.
    """
    start_time = int(time.time() * 1000)
    logger.debug(f"Navigating to page with image: {request.url}")
    
    # Enable network interception
    sb.driver.execute_cdp_cmd("Network.enable", {})
    
    # Set up a response handler
    image_data = None
    image_content_type = None
    
    def network_response_received(response: Dict[str, Any]) -> None:
        nonlocal image_data, image_content_type
        response_url = response.get("response", {}).get("url", "")
        mime_type = response.get("response", {}).get("mimeType", "")
        
        if mime_type and mime_type.startswith("image/"):
            logger.debug(f"Found image response: {response_url}, type: {mime_type}")
            
            # Get the request ID to fetch the body
            request_id = response.get("requestId")
            if request_id:
                try:
                    body_response = sb.driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
                    if body_response.get("base64Encoded", False):
                        image_data = base64.b64decode(body_response.get("body", ""))
                    else:
                        image_data = body_response.get("body", "").encode()
                    
                    image_content_type = mime_type
                    if image_data:
                        logger.debug(f"Successfully captured image data, size: {len(image_data)} bytes")
                except Exception as e:
                    logger.error(f"Error getting response body: {e}")
    
    # Register the event listener
    sb.driver.add_cdp_listener("Network.responseReceived", network_response_received)
    
    try:
        # Navigate to the URL
        sb.uc_open_with_reconnect(request.url)
        logger.debug(f"Page loaded: {request.url}")
        
        # Check for challenges
        source_bs = sb.get_beautiful_soup()
        title_tag = source_bs.title
        if title_tag and title_tag.string in CHALLENGE_TITLES:
            logger.debug("Challenge detected")
            sb.uc_gui_click_captcha()
            logger.info("Clicked captcha")

        if sb.get_title() in CHALLENGE_TITLES:
            save_screenshot(sb)
            raise HTTPException(status_code=500, detail="Could not bypass challenge")
        
        # Make sure the target image is in view to trigger network request
        try:
            sb.wait_for_element_visible(request.image_selector, timeout=request.max_timeout)
            sb.scroll_to(request.image_selector)
            logger.debug(f"Found and scrolled to image element: {request.image_selector}")
            
            # Wait a bit for image to load
            time.sleep(2)
        except Exception as e:
            logger.error(f"Error finding image element: {e}")
            raise HTTPException(status_code=404, detail=f"Image element not found: {str(e)}")
        
        # If we didn't capture the image data through the listener
        if not image_data:
            # Try to get the image source directly
            try:
                img_src = sb.get_attribute(request.image_selector, "src")
                if img_src:
                    logger.debug(f"Got image src: {img_src}")
                    # Navigate directly to the image URL to capture it
                    sb.uc_open_with_reconnect(img_src)
                    # Wait for image to load
                    time.sleep(1)
                    
                    # Take screenshot as last resort
                    if not image_data:
                        logger.debug("Taking screenshot of image as fallback")
                        temp_file = "temp_image.png"
                        sb.save_screenshot(temp_file)
                        with open(temp_file, "rb") as f:
                            image_data = f.read()
                        image_content_type = "image/png"
                        os.remove(temp_file)
            except Exception as e:
                logger.error(f"Error getting image directly: {e}")
        
        if not image_data:
            raise HTTPException(status_code=404, detail="Could not capture image data")
        
        # Disable network interception
        sb.driver.execute_cdp_cmd("Network.disable", {})
        
        # Return the image data
        file_extension = "bin"
        if image_content_type and "/" in image_content_type:
            file_extension = image_content_type.split("/")[-1]
        
        # Cast to ensure type checker knows image_data is bytes
        image_bytes = cast(bytes, image_data)
            
        return Response(
            content=image_bytes,
            media_type=image_content_type,
            headers={"Content-Disposition": f"attachment; filename=image.{file_extension}"}
        )
    
    except Exception as e:
        logger.error(f"Error during image download: {e}")
        raise HTTPException(status_code=500, detail=f"Error downloading image: {str(e)}")
    finally:
        # Clean up
        try:
            sb.driver.remove_cdp_listener("Network.responseReceived", network_response_received)
            sb.driver.execute_cdp_cmd("Network.disable", {})
        except:
            pass
