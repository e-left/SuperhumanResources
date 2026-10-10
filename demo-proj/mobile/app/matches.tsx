import { Text, View } from 'react-native';
import { Link } from 'expo-router';
import { useMutation, useQuery } from '@tanstack/react-query';
import * as Notifications from 'expo-notifications';
import { api, fixture, Match } from '../lib/api';
import { useSession } from '../lib/session';
import { Button, ErrorText, Screen, styles } from '../components/ui';
export default function Matches() {
  const { token } = useSession();
  const matches = useQuery({ queryKey: ['matches'], queryFn: () => api<Match[]>('/matches', token), enabled: !!token });
  const notifications = useQuery({ queryKey: ['notifications'], queryFn: () => api<Array<{ id: string; status: string; attempts: number; lastError: string | null }>>('/me/notifications', token), enabled: !!token, refetchInterval: token ? 5000 : false });
  const push = useMutation({ mutationFn: async () => {
    if (fixture) return 'Fixture worker records simulated notifications; no device push is sent.';
    const permission = await Notifications.requestPermissionsAsync();
    if (permission.status !== 'granted') throw new Error('Push permission not granted');
    const projectId = process.env.EXPO_PUBLIC_EAS_PROJECT_ID;
    if (!projectId) throw new Error('Set an EAS project ID for live device push');
    await Notifications.setNotificationChannelAsync('default', { name: 'FlatPal matches', importance: Notifications.AndroidImportance.DEFAULT });
    let timer: ReturnType<typeof setTimeout>;
    const expoToken = await Promise.race([
      Notifications.getExpoPushTokenAsync({ projectId }),
      new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Push registration timed out')), 15000); }),
    ]).finally(() => clearTimeout(timer!));
    await api('/me/push-token', token, { token: expoToken.data }, 'PUT');
    return 'Push token registered. Future matches can notify this device.';
  } });
  return <Screen title="Your matches">
    {!token ? <Text>Sign in on Home first.</Text> : <>
      {matches.data?.map(match => <View key={match.id} style={styles.card}><Text style={styles.title}>{match.other.name}</Text><Text style={styles.text}>{match.other.area}</Text>
        <Link href={{ pathname: '/chat/[id]', params: { id: match.id, otherId: match.other.id, name: match.other.name } }} style={styles.text}>Open chat →</Link></View>)}
      {matches.data?.length === 0 ? <Text style={styles.text}>Mutual likes appear here.</Text> : null}
      <Button title={fixture ? 'Explain simulated push' : 'Enable match notifications'} disabled={push.isPending} onPress={() => push.mutate()} />
      {push.data ? <Text style={styles.text}>{push.data}</Text> : null}
      <Text style={styles.label}>Notification activity</Text>
      {notifications.data?.map(n => <Text key={n.id} style={styles.text}>{n.status} · {n.attempts} attempt(s){n.lastError ? ` · ${n.lastError}` : ''}</Text>)}
    </>}
    <ErrorText error={matches.error ?? notifications.error ?? push.error} />
  </Screen>;
}
