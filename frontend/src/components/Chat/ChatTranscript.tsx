import { Bot, Wrench } from "lucide-react"

import type { AgentPublic } from "@/client"
import Markdown from "@/components/Chat/Markdown"
import type { ChatTurn } from "@/components/Chat/chatTurns"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Bubble, BubbleContent } from "@/components/ui/bubble"
import { Marker, MarkerContent, MarkerIcon } from "@/components/ui/marker"
import {
  Message,
  MessageAvatar,
  MessageContent,
  MessageFooter,
} from "@/components/ui/message"
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller"
import { getInitials } from "@/utils"

interface ChatTranscriptProps {
  turns: ChatTurn[]
  agent: AgentPublic
  profilePictureLink?: string
}

const ChatTranscript = ({
  turns,
  agent,
  profilePictureLink,
}: ChatTranscriptProps) => {
  return (
    <MessageScrollerProvider autoScroll defaultScrollPosition="end">
      <MessageScroller className="flex-1">
        <MessageScrollerViewport>
          <MessageScrollerContent className="mx-auto w-full max-w-3xl px-4 py-6">
            {turns.map((turn) =>
              turn.role === "user" ? (
                <MessageScrollerItem key={turn.id} messageId={turn.id} scrollAnchor>
                  <Message align="end">
                    <MessageContent>
                      {/* Put file upload UI here? */}
                      <Bubble align="end">
                        <BubbleContent>
                          <Markdown content={turn.text} />
                        </BubbleContent>
                      </Bubble>
                    </MessageContent>
                  </Message>
                </MessageScrollerItem>
              ) : (
                <MessageScrollerItem key={turn.id} messageId={turn.id}>
                  <Message align="start">
                    <MessageAvatar>
                      <Avatar>
                        {profilePictureLink ? (
                          <AvatarImage src={profilePictureLink} alt={agent.name} />
                        ) : null}
                        <AvatarFallback className="bg-zinc-600 text-white">
                          {agent.name ? (
                            getInitials(agent.name)
                          ) : (
                            <Bot className="size-4" />
                          )}
                        </AvatarFallback>
                      </Avatar>
                    </MessageAvatar>
                    <MessageContent>
                      {turn.reasoning ? (
                        <Marker className="italic">
                          <MarkerContent>{turn.reasoning}</MarkerContent>
                        </Marker>
                      ) : null}
                      {turn.toolCalls.map((call) => (
                        <Marker key={call.id}>
                          <MarkerIcon>
                            <Wrench />
                          </MarkerIcon>
                          <MarkerContent>Called {call.name}</MarkerContent>
                        </Marker>
                      ))}
                      {turn.status === "error" ? (
                        <Marker className="text-destructive">
                          <MarkerContent>
                            {turn.error || "Something went wrong."}
                          </MarkerContent>
                        </Marker>
                      ) : turn.text ? (
                        <Bubble variant="secondary" align="start">
                          <BubbleContent>
                            <Markdown content={turn.text} />
                          </BubbleContent>
                        </Bubble>
                      ) : turn.status === "streaming" ? (
                        <Bubble variant="secondary" align="start">
                          <BubbleContent>
                            <span className="shimmer">Thinking…</span>
                          </BubbleContent>
                        </Bubble>
                      ) : null}
                      {turn.status === "done" && turn.usage ? (
                        <MessageFooter>
                          {turn.usage.total_tokens.toLocaleString()} tokens
                        </MessageFooter>
                      ) : null}
                    </MessageContent>
                  </Message>
                </MessageScrollerItem>
              ),
            )}
          </MessageScrollerContent>
        </MessageScrollerViewport>
        <MessageScrollerButton />
      </MessageScroller>
    </MessageScrollerProvider>
  )
}

export default ChatTranscript
