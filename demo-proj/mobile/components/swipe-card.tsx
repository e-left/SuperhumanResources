import { Text, Image, View, useWindowDimensions } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, { useSharedValue, useAnimatedStyle, withSpring, withTiming, runOnJS } from 'react-native-reanimated';
import { Profile } from '../lib/api';
import { styles } from './ui';
export function SwipeCard({ profile, pending, onSwipe }: { profile: Profile; pending: boolean; onSwipe: (decision: 'like' | 'pass') => void }) {
  const x = useSharedValue(0), { width } = useWindowDimensions();
  const style = useAnimatedStyle(() => ({ transform: [{ translateX: x.value }, { rotate: `${x.value / 24}deg` }] }));
  const pan = Gesture.Pan().enabled(!pending).activeOffsetX([-15,15]).failOffsetY([-30,30])
    .onUpdate(event => { x.value = event.translationX; })
    .onEnd(() => {
      if (Math.abs(x.value) < 100) { x.value = withSpring(0); return; }
      const decision = x.value > 0 ? 'like' : 'pass';
      x.value = withTiming(x.value > 0 ? width : -width, { duration: 180 }, finished => {
        if (finished) { runOnJS(onSwipe)(decision); x.value = 0; }
      });
    });
  return <GestureDetector gesture={pan}><Animated.View style={[styles.card, style]}>
    {profile.photoUrl ? <Image source={{ uri: profile.photoUrl }} style={{ width: '100%', height: 180, borderRadius: 16 }} /> : <View style={{ backgroundColor: '#E7DDF2', borderRadius: 16, padding: 40, alignItems: 'center' }}><Text style={{ fontSize: 64, color: '#7351A2' }}>{profile.name[0]}</Text></View>}
    <Text style={styles.title}>{profile.name}</Text><Text style={styles.text}>{profile.bio}</Text>
    <Text style={styles.text}>{profile.area} · {profile.distanceKm?.toFixed(1)} km</Text>
    <Text style={styles.text}>CHF {profile.budgetMin}–{profile.budgetMax} · Move in {profile.moveIn.slice(0,10)}</Text>
    <Text style={styles.text}>Smoking: {profile.smoking} · Pets: {profile.pets} · Sleep: {profile.sleep}</Text>
    <Text style={styles.label}>Swipe left to pass · right to like</Text>
  </Animated.View></GestureDetector>;
}
