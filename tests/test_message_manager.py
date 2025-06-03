#!/usr/bin/env python3
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from .test_base import BaseTestCase


class TestMessageManager(BaseTestCase):
    """메시지 관리 관련 테스트"""

    async def helper_test_message_manager_update(self, existing_message_text=None, new_text="New Text", should_edit_fail=False, should_reply_fail=False):
        user_id = self.test_user_id
        mock_message = MagicMock()
        mock_message.message_id = 123
        mock_message.chat_id = user_id
        
        if existing_message_text:
            mock_message.text = existing_message_text
            self.message_manager.set_status_message(user_id, mock_message)
            
        async def mock_edit_text(*args, **kwargs):
            if should_edit_fail: 
                raise MagicMock(side_effect=Exception("Edit failed"))
            if kwargs.get('text') == mock_message.text and existing_message_text is not None: 
                return mock_message
            mock_message.text = kwargs.get('text')
            return mock_message
            
        async def mock_reply_text(*args, **kwargs):
            if should_reply_fail: 
                raise Exception("Reply failed")
            new_msg = MagicMock()
            new_msg.text = kwargs.get('text')
            return new_msg
            
        mock_message.edit_text = MagicMock(side_effect=mock_edit_text)
        mock_message.reply_text = MagicMock(side_effect=mock_reply_text)
        
        # telegram_bot의 safe_edit_message를 AsyncMock으로 패치
        with patch.object(self.flight_checker_module.telegram_bot, 'safe_edit_message', new_callable=AsyncMock) as mock_safe_edit:
            if existing_message_text:
                if should_edit_fail:
                    if should_reply_fail:
                        async def side_effect_none(*args, **kwargs): 
                            return None
                        mock_safe_edit.side_effect = side_effect_none
                        updated_message = await self.message_manager.update_status_message(
                            user_id, new_text, telegram_bot=self.flight_checker_module.telegram_bot
                        )
                    else:
                        new_reply_message = MagicMock()
                        new_reply_message.text = new_text
                        async def side_effect_reply(*args, **kwargs): 
                            return new_reply_message
                        mock_safe_edit.side_effect = side_effect_reply
                        updated_message = await self.message_manager.update_status_message(
                            user_id, new_text, telegram_bot=self.flight_checker_module.telegram_bot
                        )
                else:
                    edited_message = MagicMock()
                    edited_message.text = new_text
                    async def side_effect_edit(*args, **kwargs): 
                        return edited_message
                    mock_safe_edit.side_effect = side_effect_edit
                    updated_message = await self.message_manager.update_status_message(
                        user_id, new_text, telegram_bot=self.flight_checker_module.telegram_bot
                    )
            else:
                updated_message = await self.message_manager.update_status_message(
                    user_id, new_text, telegram_bot=self.flight_checker_module.telegram_bot
                )
                
            if existing_message_text:
                mock_safe_edit.assert_called_once()
                call_args = mock_safe_edit.call_args[0]
                self.assertEqual(call_args[1], new_text)
                if should_edit_fail and not should_reply_fail:
                    self.assertEqual(updated_message.text, new_text)
                    self.assertEqual(self.message_manager.status_messages[user_id].text, new_text)
                elif not should_edit_fail:
                    self.assertEqual(updated_message.text, new_text)
                    self.assertEqual(self.message_manager.status_messages[user_id].text, new_text)
                else: 
                    self.assertIsNone(updated_message)
                    self.assertNotIn(user_id, self.message_manager.status_messages)
            else: 
                self.assertIsNone(updated_message)
                mock_safe_edit.assert_not_called()

    def test_message_manager_update_existing_success(self):
        """기존 메시지 업데이트 성공 테스트"""
        asyncio.run(self.helper_test_message_manager_update(existing_message_text="Old Text"))
    
    def test_message_manager_update_existing_edit_fail_reply_success(self):
        """기존 메시지 편집 실패, 응답 성공 테스트"""
        asyncio.run(self.helper_test_message_manager_update(existing_message_text="Old Text", should_edit_fail=True))
    
    def test_message_manager_update_existing_edit_fail_reply_fail(self):
        """기존 메시지 편집 실패, 응답 실패 테스트"""
        asyncio.run(self.helper_test_message_manager_update(existing_message_text="Old Text", should_edit_fail=True, should_reply_fail=True))
    
    def test_message_manager_update_no_existing_message(self):
        """기존 메시지가 없는 경우 테스트"""
        asyncio.run(self.helper_test_message_manager_update(new_text="New Text"))
    
    def test_message_manager_set_and_clear(self):
        """메시지 설정 및 제거 테스트"""
        user_id = self.test_user_id
        mock_message = MagicMock()
        
        self.message_manager.set_status_message(user_id, mock_message)
        self.assertIn(user_id, self.message_manager.status_messages)
        self.assertEqual(self.message_manager.status_messages[user_id], mock_message)
        
        self.message_manager.clear_status_message(user_id)
        self.assertNotIn(user_id, self.message_manager.status_messages)


if __name__ == "__main__":
    import unittest
    unittest.main()
