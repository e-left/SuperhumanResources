import { Type } from 'class-transformer';
import { IsDateString, IsIn, IsInt, IsNumber, IsOptional, IsString, IsUUID, Length, Matches, Max, Min } from 'class-validator';
export class ProfileDto {
  @IsString() @Length(1, 60) name!: string;
  @IsString() @Length(1, 500) bio!: string;
  @IsInt() @Min(0) @Max(20000) budgetMin!: number;
  @IsInt() @Min(0) @Max(20000) budgetMax!: number;
  @IsString() @Length(1, 80) area!: string;
  @Matches(/^\d{4}-\d{2}-\d{2}$/) @IsDateString({ strict: true }) moveIn!: string;
  @IsIn(['no','yes','outside']) smoking!: string;
  @IsIn(['none','cat','dog','other']) pets!: string;
  @IsIn(['early','regular','late']) sleep!: string;
  @IsNumber() @Min(-180) @Max(180) longitude!: number;
  @IsNumber() @Min(-90) @Max(90) latitude!: number;
  @IsOptional() @IsString() @Length(1, 160) photoPath?: string;
}
export class DiscoveryDto {
  @IsOptional() @Type(() => Number) @IsInt() @Min(0) @Max(20000) budgetMin?: number;
  @IsOptional() @Type(() => Number) @IsInt() @Min(0) @Max(20000) budgetMax?: number;
  @IsOptional() @Type(() => Number) @IsInt() @Min(0) @Max(90) moveInDays = 30;
  @IsOptional() @Type(() => Number) @IsInt() @Min(1) @Max(100) radiusKm = 10;
}
export class SwipeDto {
  @IsUUID('4') targetId!: string;
  @IsIn(['like','pass']) decision!: 'like' | 'pass';
}
export class BlockDto { @IsUUID('4') targetId!: string; }
export class MessageDto { @IsString() @Length(1, 1000) text!: string; }
export class PushDto {
  @IsString() @Matches(/^(ExponentPushToken|ExpoPushToken)\[[A-Za-z0-9_-]+\]$/) token!: string;
}
export class FixtureSessionDto { @IsUUID('4') userId!: string; }
