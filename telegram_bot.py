#!/usr/bin/env python3
"""
텔레그램 봇 관련 기능들을 관리하는 모듈

이 모듈은 다음 기능들을 제공합니다:
- 텔레그램 메시지 전송 및 편집
- 키보드 생성 및 관리
- 명령어 핸들러
- 콜백 핸들러
- 메시지 관리
"""

import asyncio
import logging
from typing import Optional, Dict
from telegram import (
    Update, Message, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest, TimedOut, NetworkError

# ConfigManager import
from config_manager import config_manager

# 로거 설정
logger = logging.getLogger(__name__)

# 상수 정의
SETTING = 1  # ConversationHandler 상태


class TelegramBot:
    """텔레그램 봇 기능을 관리하는 클래스"""
    
    def __init__(self):
        self.message_manager = MessageManager()
        
    async def safe_edit_message(
        self,
        message: Message, 
        text: str, 
        parse_mode: str = None,
        reply_markup=None,
        disable_web_page_preview: bool = True,
        max_retries: int = 3
    ) -> Optional[Message]:
        """
        안전한 메시지 편집 함수
        - 편집 불가능한 경우 새 메시지 발송
        - 네트워크 에러 시 재시도
        """
        for attempt in range(max_retries):
            try:
                return await message.edit_text(
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview
                )
            except BadRequest as e:
                error_msg = str(e).lower()
                
                if "message can't be edited" in error_msg:
                    logger.warning(f"메시지 편집 불가, 새 메시지 발송: {e}")
                    try:
                        return await message.reply_text(
                            text=text,
                            parse_mode=parse_mode,
                            reply_markup=reply_markup,
                            disable_web_page_preview=disable_web_page_preview
                        )
                    except Exception as reply_error:
                        logger.error(f"새 메시지 발송도 실패: {reply_error}")
                        return None
                
                elif "message is not modified" in error_msg:
                    logger.debug("메시지 내용이 동일하여 편집하지 않음")
                    return message
                
                elif attempt < max_retries - 1:
                    logger.warning(f"메시지 편집 재시도 {attempt + 1}/{max_retries}: {e}")
                    await asyncio.sleep(1)
                    continue
                else:
                    logger.error(f"메시지 편집 최종 실패: {e}")
                    return None
                    
            except (TimedOut, NetworkError) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 지수 백오프
                    logger.warning(f"네트워크 에러, {wait_time}초 후 재시도: {e}")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"네트워크 에러 최종 실패: {e}")
                    return None
            
            except Exception as e:
                logger.error(f"예상치 못한 에러: {e}")
                return None
        
        return None

    def get_base_keyboard(self) -> ReplyKeyboardMarkup:
        """기본 키보드 버튼 생성"""
        keyboard = [
            [KeyboardButton("/monitor"), KeyboardButton("/status")],
            [KeyboardButton("/settings"), KeyboardButton("/airport")],
            [KeyboardButton("/cancel"), KeyboardButton("/help")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    def get_admin_keyboard(self) -> ReplyKeyboardMarkup:
        """관리자용 키보드 버튼 생성"""
        keyboard = [
            [KeyboardButton("/monitor"), KeyboardButton("/status")],
            [KeyboardButton("/settings"), KeyboardButton("/airport")],
            [KeyboardButton("/cancel"), KeyboardButton("/help")],
            [KeyboardButton("/allstatus"), KeyboardButton("/allcancel")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    def get_keyboard_for_user(self, user_id: int) -> ReplyKeyboardMarkup:
        """사용자 권한에 따른 키보드 반환"""
        if user_id in config_manager.ADMIN_IDS:
            return self.get_admin_keyboard()
        else:
            return self.get_base_keyboard()

    async def send_message(
        self, 
        update: Update, 
        text: str, 
        parse_mode: str = "Markdown",
        reply_markup=None,
        disable_web_page_preview: bool = True
    ) -> Optional[Message]:
        """메시지 전송"""
        try:
            return await update.message.reply_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
        except Exception as e:
            logger.error(f"메시지 전송 실패: {e}")
            return None

    async def send_message_with_keyboard(
        self, 
        update: Update, 
        text: str, 
        user_id: int = None,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True
    ) -> Optional[Message]:
        """사용자 권한에 맞는 키보드와 함께 메시지 전송"""
        if user_id is None:
            user_id = update.effective_user.id
        
        keyboard = self.get_keyboard_for_user(user_id)
        return await self.send_message(
            update, 
            text, 
            parse_mode=parse_mode,
            reply_markup=keyboard,
            disable_web_page_preview=disable_web_page_preview
        )

    async def edit_message(
        self,
        message: Message,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup=None,
        disable_web_page_preview: bool = True
    ) -> Optional[Message]:
        """메시지 편집 (safe_edit_message의 래퍼)"""
        return await self.safe_edit_message(
            message, 
            text, 
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview
        )

    async def answer_callback_query(
        self, 
        callback_query, 
        text: str, 
        show_alert: bool = False
    ) -> bool:
        """콜백 쿼리 응답"""
        try:
            await callback_query.answer(text, show_alert=show_alert)
            return True
        except Exception as e:
            logger.error(f"콜백 쿼리 응답 실패: {e}")
            return False

    async def send_notification(
        self, 
        user_id: int, 
        text: str, 
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
        application=None
    ) -> bool:
        """사용자에게 알림 메시지 전송"""
        if not application:
            logger.error("Application 객체가 필요합니다")
            return False
        
        try:
            await application.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview
            )
            return True
        except Exception as e:
            logger.error(f"사용자 {user_id}에게 알림 전송 실패: {e}")
            return False

    async def help_text(self, user_id: int = None) -> str:
        """도움말 텍스트 생성"""
        admin_help = ""
        if config_manager.ADMIN_IDS and user_id in config_manager.ADMIN_IDS:
            admin_help = (
                "\n\n👑 *관리자 명령어*\n"
                "• /allstatus - 전체 모니터링 현황\n"
                "• /allcancel - 전체 모니터링 취소"
            )
        
        return (
            "✈️ *항공권 최저가 모니터링 봇*\n"
            "\n"
            "📝 *기본 명령어*\n"
            "• /monitor - 새로운 모니터링 시작\n"
            "• /status - 모니터링 현황 확인\n"
            "• /cancel - 모니터링 취소\n"
            "\n"
            "⚙️ *설정 명령어*\n"
            "• /settings - 시간 제한 설정\n"
            "• /airport - 공항 코드 목록"
            + admin_help
        )


class MessageManager:
    """메시지 상태 관리 클래스"""
    
    def __init__(self):
        # 사용자별 상태 메시지 추적
        self.status_messages: Dict[int, Message] = {}
        # 메시지 편집 잠금 (동시 편집 방지)
        self.edit_locks: Dict[str, asyncio.Lock] = {}
    
    def get_lock(self, message_key: str) -> asyncio.Lock:
        """메시지별 편집 잠금 반환"""
        if message_key not in self.edit_locks:
            self.edit_locks[message_key] = asyncio.Lock()
        return self.edit_locks[message_key]
    
    async def update_status_message(
        self, 
        user_id: int, 
        text: str, 
        parse_mode: str = "Markdown",
        reply_markup=None,
        telegram_bot=None
    ) -> Optional[Message]:
        """사용자별 상태 메시지 업데이트"""
        if not telegram_bot:
            logger.error("TelegramBot 인스턴스가 필요합니다")
            return None
            
        message_key = f"status_{user_id}"
        
        async with self.get_lock(message_key):
            current_message = self.status_messages.get(user_id)
            
            if current_message:
                # 기존 메시지 편집 시도
                updated_message = await telegram_bot.safe_edit_message(
                    current_message, 
                    text, 
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
                
                if updated_message:
                    self.status_messages[user_id] = updated_message
                    return updated_message
                else:
                    # 편집 실패 시 새 메시지로 교체
                    del self.status_messages[user_id]
            
            return None
    
    def set_status_message(self, user_id: int, message: Message):
        """상태 메시지 등록"""
        self.status_messages[user_id] = message
    
    def clear_status_message(self, user_id: int):
        """상태 메시지 제거"""
        if user_id in self.status_messages:
            del self.status_messages[user_id]
    
    def has_status_message(self, user_id: int) -> bool:
        """사용자의 상태 메시지 존재 여부 확인"""
        return user_id in self.status_messages
