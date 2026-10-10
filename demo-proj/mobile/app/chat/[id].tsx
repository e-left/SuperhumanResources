import { useState } from 'react';
import { Text, View } from 'react-native';
import { router, useLocalSearchParams } from 'expo-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, Message } from '../../lib/api';
import { useSession } from '../../lib/session';
import { Button, ErrorText, Field, Screen, styles } from '../../components/ui';
export default function Chat() {
  const { id, otherId, name } = useLocalSearchParams<{ id: string; otherId: string; name: string }>();
  const { token, userId } = useSession(), cache = useQueryClient();
  const [text, setText] = useState('');
  const messages = useQuery({ queryKey: ['chat', id], queryFn: () => api<{ mode: string; messages: Message[] }>(`/matches/${encodeURIComponent(id)}/messages`, token), enabled: !!token && !!id, refetchInterval: query => query.state.error ? false : 3000 });
  const send = useMutation({ mutationFn: () => api(`/matches/${encodeURIComponent(id)}/messages`, token, { text }), onSuccess: () => { setText(''); cache.invalidateQueries({ queryKey: ['chat', id] }); } });
  const block = useMutation({ mutationFn: () => api('/blocks', token, { targetId: otherId }), onSuccess: () => { cache.clear(); router.replace('/matches'); } });
  return <Screen title={`Chat with ${name ?? 'your match'}`}>
    {!token ? <Text>Sign in on Home first.</Text> : <>
      {messages.data?.messages.map(message => <View key={message.id} style={[styles.card, { backgroundColor: message.senderId === userId ? '#E7DDF2' : '#FFFFFF' }]}>
        <Text style={styles.label}>{message.senderId === userId ? 'You' : name}</Text><Text style={styles.text}>{message.text}</Text>
      </View>)}
      <Field label="Message" value={text} onChange={setText} />
      <Button title="Send" disabled={!text.trim() || send.isPending || block.isPending || !!messages.error} onPress={() => send.mutate()} />
      {otherId ? <Button title="Block this user" disabled={block.isPending || send.isPending} onPress={() => block.mutate()} /> : null}
    </>}
    <ErrorText error={messages.error ?? send.error ?? block.error} />
  </Screen>;
}
